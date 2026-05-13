from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.keyboards.main import (
    back_main_keyboard,
    promo_cancel_keyboard,
)
from app.bot.screens import edit_screen, send_screen
from app.database.repository import Repository
from config.loader import config, messages, prices

logger = logging.getLogger(__name__)
router = Router()
msg = messages.messages


# ─── Реферальная программа ────────────────────────────────────────────────────

async def _build_referral_text(repo: Repository, bot_username: str, telegram_id: int) -> str | None:
    user = await repo.users.get_by_telegram_id(telegram_id)
    if not user:
        return None

    ref_link = f"https://t.me/{bot_username}?start=ref_{telegram_id}"
    invited = await repo.users.count_referrals(telegram_id)
    bonus = user.referral_bonus_days or 0

    return msg["referral_info"].format(
        inviter_days=prices.referral.inviter_bonus_days,
        invitee_days=prices.referral.invitee_bonus_days,
        ref_link=ref_link,
        invited_count=invited,
        total_bonus=bonus,
    )


@router.callback_query(F.data == "menu:referral")
async def cb_show_referral(call: CallbackQuery, repo: Repository) -> None:
    if not config.features.referral_enabled:
        await call.answer("Реферальная программа временно недоступна.", show_alert=True)
        return

    bot_username = (await call.bot.get_me()).username or config.bot.username
    text = await _build_referral_text(repo, bot_username, call.from_user.id)
    if text is None:
        await call.answer("Ошибка")
        return
    await edit_screen(call, "referral", text, reply_markup=back_main_keyboard())
    await call.answer()


@router.message(Command("referral"))
async def cmd_referral(message: Message, repo: Repository) -> None:
    if not config.features.referral_enabled:
        await message.answer("Реферальная программа временно недоступна.")
        return

    bot_username = (await message.bot.get_me()).username or config.bot.username
    text = await _build_referral_text(repo, bot_username, message.from_user.id)
    if text is None:
        await message.answer("Сначала напиши /start")
        return
    await send_screen(message, "referral", text, reply_markup=back_main_keyboard())


# ─── Промокоды ────────────────────────────────────────────────────────────────

class PromoStates(StatesGroup):
    waiting_code = State()


@router.callback_query(F.data == "menu:promo")
async def cb_ask_promo(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_code)
    await edit_screen(call, "promo", msg["promo_ask"], reply_markup=promo_cancel_keyboard())
    await call.answer()


@router.message(Command("promo"))
async def cmd_promo(message: Message, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_code)
    await send_screen(message, "promo", msg["promo_ask"], reply_markup=promo_cancel_keyboard())


@router.message(PromoStates.waiting_code)
async def handle_promo_code(message: Message, state: FSMContext, repo: Repository) -> None:
    await state.clear()
    code = message.text.strip().upper()

    user = await repo.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(msg["promo_invalid"], reply_markup=back_main_keyboard())
        return

    sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if not sub:
        await message.answer(msg["promo_no_sub"], reply_markup=back_main_keyboard())
        return

    promo = await repo.promos.get_by_code(code)
    if not promo:
        await message.answer(msg["promo_invalid"], reply_markup=back_main_keyboard())
        return

    if await repo.promos.has_used(promo.id, user.id):
        await message.answer(msg["promo_invalid"], reply_markup=back_main_keyboard())
        return

    await repo.subscriptions.extend(sub.id, promo.days)
    await repo.promos.record_use(promo.id, user.id)
    await repo.commit()

    from app.services.remnawave import remna
    updated_sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if updated_sub and updated_sub.expires_at and user.remnawave_uuid:
        expire_iso = updated_sub.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        await remna.update_user(uuid=user.remnawave_uuid, expire_at=expire_iso)

    await message.answer(
        msg["promo_success"].format(days=promo.days),
        parse_mode="HTML",
        reply_markup=back_main_keyboard(),
    )


# ─── Поддержка / Канал — отдельные команды ──────────────────────────────────

@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Поддержка", url=config.links.support)]]
    )
    await message.answer("Обратись в поддержку:", reply_markup=kb)
