from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import (
    pay_url_keyboard,
    payment_method_keyboard,
    period_keyboard,
    plan_keyboard,
    renew_period_keyboard,
    trial_keyboard,
)
from app.bot.screens import edit_screen, send_screen
from app.database.models import PaymentSystem, PlanType
from app.database.repository import Repository
from app.services.cryptobot import cryptobot
from app.services.subscription import activate_subscription
from app.services.yukassa import yukassa
from config.loader import config, messages, prices

logger = logging.getLogger(__name__)
router = Router()

btn = messages.buttons
msg = messages.messages

# vpnbot/app/bot/handlers/payment.py

async def _send_existing_trial_link(call: CallbackQuery, repo: Repository) -> None:
    """
    Ничего не пишет в БД. Только читает и отправляет пользователю его старую trial-ссылку.
    """
    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if not user:
        await call.answer("Ошибка. Напиши /start", show_alert=True)
        return

    trial_sub = await repo.subscriptions.get_last_by_user_id_and_plan(user.id, PlanType.trial)
    url = trial_sub.subscription_url if (trial_sub and trial_sub.subscription_url) else None

    # Текст "пробник уже использован" у тебя уже есть в messages.yaml
    # trial_already_used <!--citation:4-->
    await edit_screen(call, "trial", msg["trial_already_used"], reply_markup=plan_keyboard())
    await call.answer()

    if url:
        # subscription_link тоже уже есть <!--citation:4-->
        link_text = msg["subscription_link"].format(link=url)
        await call.message.answer(link_text, parse_mode="HTML")
    else:
        await call.message.answer("Ссылка от пробного периода не найдена в базе. Напиши в поддержку.")

# ────────────────────────────────────────────────────
# Entry: «Подключить VPN» (menu callback or /plans command)
# ────────────────────────────────────────────────────

def _plans_text() -> str:
    return msg["choose_plan"]


@router.callback_query(F.data == "menu:subscribe")
async def cb_show_plans(call: CallbackQuery) -> None:
    await edit_screen(call, "plans", _plans_text(), reply_markup=plan_keyboard())
    await call.answer()


@router.callback_query(F.data == "menu:change_plan")
async def cb_change_plan(call: CallbackQuery) -> None:
    """Смена подписки (выбор нового плана)"""
    await edit_screen(call, "plans", _plans_text(), reply_markup=plan_keyboard())
    await call.answer()


@router.callback_query(F.data == "menu:renew")
async def cb_renew_subscription(call: CallbackQuery, repo: Repository) -> None:
    """Продление действующей подписки"""
    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if not user:
        await call.answer("Ошибка. Напиши /start", show_alert=True)
        return

    sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if not sub:
        await call.answer("У вас нет активной подписки", show_alert=True)
        return

    # Определяем периоды в зависимости от типа подписки
    plan_key = sub.plan.value
    plan_prices = prices.standard if plan_key == "standard" else prices.extended

    text = msg["renew_period"]
    await edit_screen(
        call,
        "renew",
        text,
        reply_markup=renew_period_keyboard(plan_key, plan_prices.days_options),
    )
    await call.answer()


# ────────────────────────────────────────────────────
# Renew subscription: period selected → payment method
# ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("renew:"))
async def cb_renew_period_selected(call: CallbackQuery, repo: Repository) -> None:
    """Обработчик продления подписки - выбор метода оплаты"""
    parts = call.data.split(":")
    plan_key = parts[1]
    days = int(parts[2])
    price_rub = float(parts[3])
    price_usdt = float(parts[4])

    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if not user:
        await call.answer("Ошибка. Напиши /start", show_alert=True)
        return

    # Определяем количество устройств по плану
    if plan_key == "standard":
        devices_limit = 2
    else:  # extended
        devices_limit = 5
    
    plan_label = "стандартная" if plan_key == "standard" else "расширенная"
    price_str = f"{price_rub:.0f}₽ или {price_usdt:.1f} USDT"

    text = msg["payment_invoice"].format(
        plan=plan_label, 
        days=days, 
        price=price_str,
        devices=devices_limit
    )
    await edit_screen(
        call,
        "payment",
        text,
        reply_markup=payment_method_keyboard(plan_key, days, price_rub, price_usdt),
    )
    await call.answer()

@router.callback_query(F.data.startswith("plan:"))
async def cb_plan_selected(call: CallbackQuery, repo: Repository) -> None:
    plan_key = call.data.split(":")[1]  # trial / standard / extended

    if plan_key == "trial":
        await _handle_trial_info(call, repo)
        return

    plan_prices = prices.standard if plan_key == "standard" else prices.extended

    text = msg["choose_period"]
    await edit_screen(
        call,
        "period",
        text,
        reply_markup=period_keyboard(plan_key, plan_prices.days_options),
    )
    await call.answer()


# vpnbot/app/bot/handlers/payment.py

async def _handle_trial_info(call: CallbackQuery, repo: Repository) -> None:
    user = await repo.users.get_by_telegram_id(call.from_user.id)

    # ВАЖНО: если пробник уже использован — показываем его старую ссылку (без записей в БД)
    if user and user.trial_used:
        await _send_existing_trial_link(call, repo)
        return

    if not config.features.trial_enabled:
        await call.answer("Пробный период временно недоступен.", show_alert=True)
        return

    text = msg["trial_info"]
    await edit_screen(call, "trial", text, reply_markup=trial_keyboard(config.links.channel))
    await call.answer()

# ────────────────────────────────────────────────────
# Trial: check subscription
# ────────────────────────────────────────────────────

# vpnbot/app/bot/handlers/payment.py

@router.callback_query(F.data == "trial:check")
async def cb_trial_check(call: CallbackQuery, repo: Repository, bot: Bot) -> None:
    # 1) Если пробник уже был — просто вернуть старую ссылку (ничего не меняя)
    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if user and user.trial_used:
        await _send_existing_trial_link(call, repo)
        return

    # 2) Проверяем подписку на канал только для "первой" активации пробника
    try:
        member = await bot.get_chat_member(config.links.channel_id, call.from_user.id)
        is_member = member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.warning("Failed to check channel membership: %s", e)
        is_member = False

    if not is_member:
        await call.answer(msg["trial_check_sub"], show_alert=True)
        return

    # 3) Активируем пробник
    days = config.features.trial_days
    sub_url = await activate_subscription(
        repo=repo,
        telegram_id=call.from_user.id,
        username=call.from_user.username,
        plan=PlanType.trial,
        days=days,
    )

    # 4) Если не получилось — НЕ помечаем trial_used
    if not sub_url:
        await call.answer("Ошибка активации. Попробуй позже.", show_alert=True)
        return

    # 5) Успешно: теперь можно пометить trial_used
    await repo.users.mark_trial_used(call.from_user.id)
    await repo.commit()

    text = msg["trial_activated"].format(days=days)
    await edit_screen(call, "trial", text, reply_markup=plan_keyboard())
    await call.answer()

    link_text = msg["subscription_link"].format(link=sub_url)
    await call.message.answer(link_text, parse_mode="HTML")
# ────────────────────────────────────────────────────
# Period selected → payment method
# ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("period:"))
async def cb_period_selected(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    plan_key = parts[1]
    days = int(parts[2])
    price_rub = float(parts[3])
    price_usdt = float(parts[4])

    # Определяем количество устройств по плану
    if plan_key == "standard":
        devices_limit = 2
    else:  # extended
        devices_limit = 5
    
    plan_label = "стандартная" if plan_key == "standard" else "расширенная"
    price_str = f"{price_rub:.0f}₽ или {price_usdt:.1f} USDT"

    text = msg["payment_invoice"].format(
        plan=plan_label, 
        days=days, 
        price=price_str,
        devices=devices_limit
    )
    await edit_screen(
        call,
        "payment",
        text,
        reply_markup=payment_method_keyboard(plan_key, days, price_rub, price_usdt),
    )
    await call.answer()


# ────────────────────────────────────────────────────
# Create payment
# ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay:yukassa:"))
async def cb_pay_yukassa(call: CallbackQuery, repo: Repository) -> None:
    parts = call.data.split(":")
    plan_key = parts[2]
    days = int(parts[3])
    price_rub = float(parts[4])

    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if not user:
        await call.answer("Ошибка. Напиши /start", show_alert=True)
        return

    plan = PlanType(plan_key)
    payment = await repo.payments.create(
        user_id=user.id,
        plan=plan,
        days=days,
        amount=price_rub,
        currency="RUB",
        payment_system=PaymentSystem.yukassa,
    )
    await repo.commit()

    plan_label = "Стандартный" if plan_key == "standard" else "Расширенный"
    result = await yukassa.create_payment(
        amount=price_rub,
        description=f"VPN {plan_label} {days} дней",
        payment_id=payment.id,
        metadata={"telegram_id": str(call.from_user.id)},
    )

    if not result:
        await call.answer("Ошибка создания платежа. Попробуй позже.", show_alert=True)
        return

    await repo.payments.set_status(payment.id, payment.status, result["external_id"])
    await repo.commit()

    await edit_screen(
        call,
        "payment_link",
        "💳 Перейди по ссылке для оплаты.\nПосле оплаты подписка активируется автоматически.",
        reply_markup=pay_url_keyboard(result["confirmation_url"]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:crypto:"))
async def cb_pay_crypto(call: CallbackQuery, repo: Repository) -> None:
    parts = call.data.split(":")
    plan_key = parts[2]
    days = int(parts[3])
    price_usdt = float(parts[4])

    user = await repo.users.get_by_telegram_id(call.from_user.id)
    if not user:
        await call.answer("Ошибка. Напиши /start", show_alert=True)
        return

    plan = PlanType(plan_key)
    payment = await repo.payments.create(
        user_id=user.id,
        plan=plan,
        days=days,
        amount=price_usdt,
        currency="USDT",
        payment_system=PaymentSystem.cryptobot,
    )
    await repo.commit()

    plan_label = "Стандартный" if plan_key == "standard" else "Расширенный"
    result = await cryptobot.create_invoice(
        amount_usdt=price_usdt,
        description=f"VPN {plan_label} {days} дней",
        payment_id=payment.id,
    )

    if not result:
        await call.answer("Ошибка создания платежа. Попробуй позже.", show_alert=True)
        return

    await repo.payments.set_status(payment.id, payment.status, result["external_id"])
    await repo.commit()

    await edit_screen(
        call,
        "payment_link",
        "🪙 Перейди в CryptoBot для оплаты.\nПосле оплаты подписка активируется автоматически.",
        reply_markup=pay_url_keyboard(result["pay_url"]),
    )
    await call.answer()


# ────────────────────────────────────────────────────
# Manual payment check (fallback)
# ────────────────────────────────────────────────────

@router.callback_query(F.data == "pay:check")
async def cb_pay_check(call: CallbackQuery) -> None:
    await call.answer(
        "Платёж проверяется автоматически. Если статус не обновился — подожди пару минут.",
        show_alert=True,
    )


# ────────────────────────────────────────────────────
# Back navigation
# ────────────────────────────────────────────────────

@router.callback_query(F.data == "back:plans")
async def cb_back_plans(call: CallbackQuery) -> None:
    await edit_screen(call, "plans", _plans_text(), reply_markup=plan_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("back:period:"))
async def cb_back_period(call: CallbackQuery) -> None:
    plan_key = call.data.split(":")[-1]
    plan_prices = prices.standard if plan_key == "standard" else prices.extended
    text = msg["choose_period"]
    await edit_screen(
        call,
        "period",
        text,
        reply_markup=period_keyboard(plan_key, plan_prices.days_options),
    )
    await call.answer()
