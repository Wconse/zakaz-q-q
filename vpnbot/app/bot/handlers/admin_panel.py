from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters.admin import AdminFilter
from app.bot.keyboards.admin import (
    admin_broadcast_keyboard,
    admin_grant_plan_keyboard,
    admin_main_keyboard,
    admin_promo_keyboard,
    admin_user_actions_keyboard,
    admin_users_keyboard,
    confirm_delete_keyboard,
)
from app.bot.screens import edit_screen, send_screen
from app.database.repository import Repository
from app.services.remnawave import remna
from config.loader import config, messages

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

btn = messages.buttons
msg = messages.messages


class AdminStates(StatesGroup):
    find_user = State()
    edit_days = State()
    edit_devices = State()
    edit_traffic = State()
    create_promo_name = State()
    create_promo_days = State()
    delete_promo = State()
    grant_days = State()
    toggle_trial = State()


# ─── Entry: «Админ-панель» (callback) и команда /admin ────────────────────────

@router.callback_query(F.data == "menu:admin")
async def cb_admin_panel(call: CallbackQuery) -> None:
    await edit_screen(call, "admin", msg["admin_welcome"], reply_markup=admin_main_keyboard())
    await call.answer()


@router.message(Command("admin"))
async def cmd_admin_panel(message: Message) -> None:
    await send_screen(message, "admin", msg["admin_welcome"], reply_markup=admin_main_keyboard())


# ─── Раздел «Пользователи» ────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:admin_users")
async def cb_admin_users(call: CallbackQuery) -> None:
    await edit_screen(
        call,
        "admin_users",
        "👥 <b>Управление пользователями</b>\n\nВыбери действие:",
        reply_markup=admin_users_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:users:all")
async def cb_admin_all_users(call: CallbackQuery, repo: Repository) -> None:
    users = await repo.users.get_all()
    lines = [f"👥 <b>Всего пользователей: {len(users)}</b>\n"]
    for u in users[:50]:
        username = f"@{u.username}" if u.username else "—"
        lines.append(f"• <code>{u.telegram_id}</code> {username}")
    if len(users) > 50:
        lines.append(f"\n<i>...и ещё {len(users) - 50}</i>")
    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:users:new")
async def cb_admin_new_users(call: CallbackQuery, repo: Repository) -> None:
    users = await repo.users.get_new_since(24)
    lines = [f"🆕 <b>Новые за 24ч: {len(users)}</b>\n"]
    for u in users:
        username = f"@{u.username}" if u.username else "—"
        lines.append(f"• <code>{u.telegram_id}</code> {username} — {u.created_at.strftime('%H:%M')}")
    text = "\n".join(lines) if lines else "Нет новых пользователей."
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:users:blocked")
async def cb_admin_blocked_users(call: CallbackQuery, repo: Repository) -> None:
    users = await repo.users.get_blocked()
    lines = [f"🚫 <b>Заблокировали бота: {len(users)}</b>\n"]
    for u in users[:50]:
        username = f"@{u.username}" if u.username else "—"
        lines.append(f"• <code>{u.telegram_id}</code> {username}")
    text = "\n".join(lines) if lines else "Нет заблокировавших пользователей."
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "admin:users:find")
async def cb_admin_find_user(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.find_user)
    await call.message.answer(msg["admin_ask_user_id"])
    await call.answer()


@router.message(AdminStates.find_user)
async def handle_find_user(message: Message, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    query = message.text.strip()

    if query.startswith("@"):
        user = await repo.users.get_by_username(query)
    else:
        try:
            user = await repo.users.get_by_telegram_id(int(query))
        except ValueError:
            user = await repo.users.get_by_username(query)

    if not user:
        await message.answer(msg["admin_no_user"])
        return

    await _show_user_info(message, repo, user.telegram_id)


@router.callback_query(F.data.startswith("admin:user:info:"))
async def cb_admin_user_info(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    await _show_user_info(call.message, repo, tg_id)
    await call.answer()


async def _show_user_info(message: Message, repo: Repository, telegram_id: int) -> None:
    user = await repo.users.get_by_telegram_id(telegram_id)
    if not user:
        await message.answer(msg["admin_no_user"])
        return

    sub = await repo.subscriptions.get_active_by_user_id(user.id)

    devices_used = 0
    traffic_limit = "—"
    if user.remnawave_uuid:
        remna_user = await remna.get_user_by_uuid(user.remnawave_uuid)
        if remna_user:
            devices_used = remna_user.devices_count
            # Try to get traffic limit from Remnawave
            if hasattr(remna_user, 'data_limit') and remna_user.data_limit:
                traffic_limit = f"{remna_user.data_limit / (1024**3):.0f} ГБ"

    plan = messages.plans.get(sub.plan.value, sub.plan.value) if sub else "—"
    expire = sub.expires_at.strftime("%d.%m.%Y %H:%M") if sub and sub.expires_at else "—"
    
    # Берём devices_limit из подписки (админ может менять)
    devices_limit = sub.devices_limit if sub else 0
    
    status = "✅ Активна" if sub else "❌ Нет подписки"
    username = f"@{user.username}" if user.username else "—"
    
    # Trial status
    trial_status = "✅ Использован" if user.trial_used else "❌ Не использован"
    
    # Referrals count
    referrals_count = await repo.users.count_referrals(telegram_id)
    
    # Used promos count
    used_promos = await repo.promos.get_used_promos_by_user(user.id)
    promos_count = len(used_promos)

    text = msg["admin_user_info"].format(
        telegram_id=telegram_id,
        username=username,
        first_name=user.first_name or "—",
        created_at=user.created_at.strftime("%d.%m.%Y"),
        plan=plan,
        devices_used=devices_used,
        devices_limit=devices_limit,
        expire_date=expire,
        status=status,
    )
    
    # Add additional info
    text += f"\n\n📈 Расход трафика: 0 ГБ из {traffic_limit}"
    text += f"\n🎁 Пробный период: {trial_status}"
    text += f"\n👥 Пригласил: {referrals_count} человек"
    text += f"\n🎫 Применено промокодов: {promos_count}"
    
    from app.bot.keyboards.admin import admin_user_actions_keyboard
    await message.answer(text, parse_mode="HTML", reply_markup=admin_user_actions_keyboard(telegram_id))


# ─── Выдача подписки ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:grant:"))
async def cb_admin_grant_start(call: CallbackQuery) -> None:
    tg_id = int(call.data.split(":")[-1])
    await call.message.answer(
        f"🎁 <b>Выдача подписки</b>\n\nПользователь: <code>{tg_id}</code>\n\nВыбери тип подписки:",
        parse_mode="HTML",
        reply_markup=admin_grant_plan_keyboard(tg_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:grant:plan:"))
async def cb_admin_grant_plan_chosen(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    plan_key = parts[3]
    tg_id = int(parts[4])

    await state.update_data(grant_telegram_id=tg_id, grant_plan=plan_key)
    await state.set_state(AdminStates.grant_days)

    plan_labels = {"trial": "Пробный", "standard": "Стандартный", "extended": "Расширенный"}
    label = plan_labels.get(plan_key, plan_key)

    await call.message.answer(
        f"📅 Выбран тип: <b>{label}</b>\n\nВведи количество дней подписки:",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminStates.grant_days)
async def handle_grant_days(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    tg_id: int = data["grant_telegram_id"]
    plan_key: str = data["grant_plan"]
    await state.clear()

    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0.")
        return

    user = await repo.users.get_by_telegram_id(tg_id)
    if not user:
        await message.answer(msg["admin_no_user"])
        return

    from app.database.models import PlanType
    from app.services.subscription import activate_subscription

    try:
        plan_enum = PlanType(plan_key)
    except ValueError:
        await message.answer(f"❌ Неизвестный тип подписки: {plan_key}")
        return

    sub_url = await activate_subscription(
        repo=repo,
        telegram_id=tg_id,
        username=user.username,
        plan=plan_enum,
        days=days,
    )

    plan_labels = {"trial": "Пробный", "standard": "Стандартный", "extended": "Расширенный"}
    label = plan_labels.get(plan_key, plan_key)

    if sub_url:
        result_text = (
            f"✅ <b>Подписка выдана!</b>\n\n"
            f"👤 Пользователь: <code>{tg_id}</code>\n"
            f"📦 Тип: <b>{label}</b>\n"
            f"📅 Дней: <b>{days}</b>\n"
            f"🔗 Ссылка: <code>{sub_url}</code>"
        )
    else:
        result_text = (
            f"⚠️ Подписка сохранена в БД, но Remnawave вернул ошибку.\n\n"
            f"👤 Пользователь: <code>{tg_id}</code>\n"
            f"📦 Тип: <b>{label}</b>\n"
            f"📅 Дней: <b>{days}</b>"
        )

    await message.answer(result_text, parse_mode="HTML")

    try:
        notify_text = (
            f"🎁 <b>Администратор выдал вам подписку!</b>\n\n"
            f"📦 Тип: <b>{label}</b>\n"
            f"📅 Срок: <b>{days} дн.</b>"
        )
        if sub_url:
            notify_text += f"\n🔗 Ваша ссылка:\n<code>{sub_url}</code>"
        await message.bot.send_message(tg_id, notify_text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Could not notify user %d about granted sub: %s", tg_id, e)


# ─── Действия над пользователем: дни ──────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:days:"))
async def cb_admin_edit_days(call: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(call.data.split(":")[-1])
    await state.update_data(pending_telegram_id=tg_id)
    await state.set_state(AdminStates.edit_days)
    await call.message.answer(msg["admin_ask_days"])
    await call.answer()


@router.message(AdminStates.edit_days)
async def handle_edit_days(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    tg_id = data["pending_telegram_id"]
    await state.clear()

    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи целое число.")
        return

    user = await repo.users.get_by_telegram_id(tg_id)
    if not user:
        await message.answer(msg["admin_no_user"])
        return

    sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if not sub:
        await message.answer("❌ У пользователя нет активной подписки.")
        return

    await repo.subscriptions.extend(sub.id, days)
    await repo.commit()

    updated_sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if user.remnawave_uuid and updated_sub and updated_sub.expires_at:
        expire_iso = updated_sub.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        await remna.update_user(uuid=user.remnawave_uuid, expire_at=expire_iso)

    new_date = updated_sub.expires_at.strftime("%d.%m.%Y") if updated_sub and updated_sub.expires_at else "—"
    await message.answer(msg["admin_days_updated"].format(days=days, expire_date=new_date), parse_mode="HTML")


# ─── Действия над пользователем: устройства ───────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:devices:"))
async def cb_admin_edit_devices(call: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(call.data.split(":")[-1])
    await state.update_data(pending_telegram_id=tg_id)
    await state.set_state(AdminStates.edit_devices)
    await call.message.answer(msg["admin_ask_devices"])
    await call.answer()


@router.message(AdminStates.edit_devices)
async def handle_edit_devices(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    tg_id = data["pending_telegram_id"]
    await state.clear()

    try:
        devices = int(message.text.strip())
        if devices < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0.")
        return

    user = await repo.users.get_by_telegram_id(tg_id)
    if not user:
        await message.answer(msg["admin_no_user"])
        return

    sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if not sub:
        await message.answer("❌ У пользователя нет активной подписки.")
        return

    await repo.subscriptions.set_devices_limit(sub.id, devices)
    await repo.commit()

    if user.remnawave_uuid:
        await remna.update_user(uuid=user.remnawave_uuid, hwid_device_limit=devices)

    await message.answer(msg["admin_devices_updated"].format(devices=devices), parse_mode="HTML")


# ─── Действия над пользователем: удаление ─────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:delete:"))
async def cb_admin_delete_confirm(call: CallbackQuery) -> None:
    tg_id = int(call.data.split(":")[-1])
    await call.message.answer(
        f"⚠️ Удалить пользователя <code>{tg_id}</code>?\nДанные в панели будут удалены, пробник сохранится.",
        parse_mode="HTML",
        reply_markup=confirm_delete_keyboard(tg_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:user:confirm_delete:"))
async def cb_admin_delete_execute(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])

    user = await repo.users.get_by_telegram_id(tg_id)
    if user and user.remnawave_uuid:
        await remna.delete_user(user.remnawave_uuid)

    trial_used = user.trial_used if user else False
    await repo.users.delete(tg_id)
    await repo.commit()

    if trial_used:
        from app.database.models import User
        stub = User(telegram_id=tg_id, trial_used=True)
        repo.session.add(stub)
        await repo.commit()

    await call.message.edit_text(msg["admin_user_deleted"].format(telegram_id=tg_id), parse_mode="HTML")
    await call.answer()


# ─── Действия над пользователем: трафик ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:traffic:"))
async def cb_admin_edit_traffic(call: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(call.data.split(":")[-1])
    await state.update_data(pending_telegram_id=tg_id)
    await state.set_state(AdminStates.edit_traffic)
    await call.message.answer("📈 Введи новый лимит трафика (в ГБ):")
    await call.answer()


@router.message(AdminStates.edit_traffic)
async def handle_edit_traffic(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    tg_id = data["pending_telegram_id"]
    await state.clear()

    try:
        traffic_gb = int(message.text.strip())
        if traffic_gb < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0.")
        return

    user = await repo.users.get_by_telegram_id(tg_id)
    if not user:
        await message.answer(msg["admin_no_user"])
        return

    if user.remnawave_uuid:
        traffic_bytes = traffic_gb * (1024**3)
        await remna.update_user(uuid=user.remnawave_uuid, data_limit=traffic_bytes)

    await message.answer(f"✅ Лимит трафика обновлен на <b>{traffic_gb} ГБ</b>", parse_mode="HTML")


# ─── Действия над пользователем: пробный период ───────────────────────────────

@router.callback_query(F.data.startswith("admin:user:trial:"))
async def cb_admin_toggle_trial(call: CallbackQuery) -> None:
    tg_id = int(call.data.split(":")[-1])
    user = await call.bot.get_chat(tg_id) if hasattr(call.bot, 'get_chat') else None
    
    trial_status = "✅ Использован" if (hasattr(user, 'trial_used') and user.trial_used) else "❌ Не использован"
    
    await call.message.answer(
        f"🎁 <b>Управление пробным периодом</b>\n\n"
        f"Пользователь: <code>{tg_id}</code>\n"
        f"Статус: {trial_status}\n\n"
        f"Выбери действие:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить как использованный", callback_data=f"admin:trial:set_used:{tg_id}")],
            [InlineKeyboardButton(text="❌ Отметить как неиспользованный", callback_data=f"admin:trial:set_unused:{tg_id}")],
            [InlineKeyboardButton(text=btn["back"], callback_data=f"admin:user:info:{tg_id}")],
        ])
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:trial:set_used:"))
async def cb_admin_trial_set_used(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    await repo.users.mark_trial_used(tg_id)
    await repo.commit()
    await call.message.edit_text("✅ Пробный период отмечен как использованный", parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("admin:trial:set_unused:"))
async def cb_admin_trial_set_unused(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    await repo.users.mark_trial_unused(tg_id)
    await repo.commit()
    await call.message.edit_text("✅ Пробный период отмечен как неиспользованный", parse_mode="HTML")
    await call.answer()


# ─── Действия над пользователем: приглашенные ─────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:referrals:"))
async def cb_admin_referrals_list(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    referrals = await repo.users.get_referrals(tg_id)
    
    if not referrals:
        await call.message.answer(f"👥 Пользователь <code>{tg_id}</code> не пригласил никого.", parse_mode="HTML")
        await call.answer()
        return
    
    from app.bot.keyboards.admin import admin_referral_actions_keyboard
    for ref in referrals[:10]:
        text = f"👤 <b>Приглашенный пользователь</b>\n\n"
        text += f"ID: <code>{ref.telegram_id}</code>\n"
        text += f"Username: @{ref.username}\n"
        text += f"Имя: {ref.first_name or '—'}\n"
        text += f"Зарегистрирован: {ref.created_at.strftime('%d.%m.%Y')}"
        
        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=admin_referral_actions_keyboard(tg_id, ref.telegram_id)
        )
    
    if len(referrals) > 10:
        await call.message.answer(f"<i>...и ещё {len(referrals) - 10} приглашенных</i>", parse_mode="HTML")
    
    await call.answer()


@router.callback_query(F.data.startswith("admin:user:unlink_referral:"))
async def cb_admin_unlink_referral(call: CallbackQuery, repo: Repository) -> None:
    parts = call.data.split(":")
    referrer_id = int(parts[4])
    referral_id = int(parts[5])
    
    await repo.users.clear_referrer(referral_id)
    await repo.commit()
    
    await call.message.edit_text(
        f"✅ Привязка удалена. Пользователь <code>{referral_id}</code> больше не связан с приглашением.",
        parse_mode="HTML"
    )
    await call.answer()


# ─── Действия над пользователем: промокоды ────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:promos:"))
async def cb_admin_user_promos(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    user = await repo.users.get_by_telegram_id(tg_id)
    
    if not user:
        await call.message.answer(msg["admin_no_user"])
        await call.answer()
        return
    
    used_promos = await repo.promos.get_used_promos_by_user(user.id)
    
    if not used_promos:
        await call.message.answer(
            f"🎫 Пользователь <code>{tg_id}</code> не применил ни одного промокода.",
            parse_mode="HTML"
        )
        await call.answer()
        return
    
    text = f"🎫 <b>Применены промокоды</b>\n\n"
    for promo, use in used_promos[:20]:
        text += f"<code>{promo.code}</code> — +{promo.days} дн. ({use.used_at.strftime('%d.%m.%Y')})\n"
    
    await call.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Очистить список", callback_data=f"admin:user:clear_promos:{tg_id}")],
            [InlineKeyboardButton(text=btn["back"], callback_data=f"admin:user:info:{tg_id}")],
        ])
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:user:clear_promos:"))
async def cb_admin_clear_user_promos(call: CallbackQuery, repo: Repository) -> None:
    tg_id = int(call.data.split(":")[-1])
    user = await repo.users.get_by_telegram_id(tg_id)
    
    if not user:
        await call.message.answer(msg["admin_no_user"])
        await call.answer()
        return
    
    used_promos = await repo.promos.get_used_promos_by_user(user.id)
    
    for promo, use in used_promos:
        await repo.promos.delete_use(promo.id, user.id)
    
    await repo.commit()
    await call.message.edit_text("✅ История использования промокодов очищена", parse_mode="HTML")
    await call.answer()


# ─── Раздел «Промокоды» ───────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:admin_promo")
async def cb_admin_promo(call: CallbackQuery) -> None:
    await edit_screen(
        call,
        "admin_promo",
        "🎁 <b>Управление промокодами</b>\n\nВыбери действие:",
        reply_markup=admin_promo_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "admin:promo:create")
async def cb_promo_create_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.create_promo_name)
    await call.message.answer(msg["admin_ask_promo_name"])
    await call.answer()


@router.message(AdminStates.create_promo_name)
async def handle_promo_name(message: Message, state: FSMContext) -> None:
    code = message.text.strip().upper()
    if not code.isalnum():
        await message.answer("❌ Код должен содержать только латинские буквы и цифры.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.create_promo_days)
    await message.answer(msg["admin_ask_promo_days"])


@router.message(AdminStates.create_promo_days)
async def handle_promo_days(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    code = data["promo_code"]
    await state.clear()

    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0.")
        return

    await repo.promos.create(code=code, days=days, created_by=message.from_user.id)
    await repo.commit()
    await message.answer(msg["admin_promo_created"].format(code=code, days=days), parse_mode="HTML")


@router.callback_query(F.data == "admin:promo:delete")
async def cb_promo_delete_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.delete_promo)
    await call.message.answer(msg["admin_ask_delete_promo"])
    await call.answer()


@router.message(AdminStates.delete_promo)
async def handle_promo_delete(message: Message, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    code = message.text.strip().upper()
    deleted = await repo.promos.delete_by_code(code)
    await repo.commit()
    if deleted:
        await message.answer(msg["admin_promo_deleted"].format(code=code), parse_mode="HTML")
    else:
        await message.answer(msg["admin_promo_not_found"])


@router.callback_query(F.data == "admin:promo:list")
async def cb_promo_list(call: CallbackQuery, repo: Repository) -> None:
    promos = await repo.promos.get_all()
    if not promos:
        await call.message.answer(msg["admin_promo_list_empty"])
        await call.answer()
        return

    lines = ["📋 <b>Активные промокоды:</b>\n"]
    for p in promos:
        lines.append(msg["admin_promo_list_item"].format(code=p.code, days=p.days, uses=len(p.uses)))
    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()


# ─── Раздел «Рассылка» ────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:admin_broadcast")
async def cb_admin_broadcast(call: CallbackQuery) -> None:
    await edit_screen(
        call,
        "admin_broadcast",
        "📣 <b>Рассылка</b>\n\nВыбери тип:",
        reply_markup=admin_broadcast_keyboard(),
    )
    await call.answer()