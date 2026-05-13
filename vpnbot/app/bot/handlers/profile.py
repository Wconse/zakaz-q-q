from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import profile_keyboard
from app.bot.screens import edit_screen, send_screen
from app.database.repository import Repository
from config.loader import messages

logger = logging.getLogger(__name__)
router = Router()

msg = messages.messages


async def _build_profile_text(repo: Repository, telegram_id: int) -> tuple[str, str | None, int, str]:
    """Возвращает (text, sub_type, devices_limit, traffic_limit)"""
    user = await repo.users.get_by_telegram_id(telegram_id)
    if not user:
        return msg["profile_no_sub"], None, 0, "—"

    sub = await repo.subscriptions.get_active_by_user_id(user.id)
    if not sub:
        return msg["profile_no_sub"], None, 0, "—"

    # Берём devices_limit из подписки (админ может менять)
    devices_limit = sub.devices_limit

    # Traffic limit - информационно
    if sub.plan.value == "standard":
        traffic_limit = "20 ГБ"
    elif sub.plan.value == "extended":
        traffic_limit = "40 ГБ"
    else:  # trial
        traffic_limit = "5 ГБ"

    # Форматируем дату истечения
    expire_date = "—"
    if sub.expires_at:
        expire_date = sub.expires_at.strftime("%d.%m.%Y")
    
    # Получаем ссылку для подключения
    connection_link = sub.subscription_url or "—"

    plan_name = sub.plan.value.capitalize()
    
    text = msg["profile"].format(
        plan=plan_name,
        expire_date=expire_date,
        devices_limit=devices_limit,
        traffic_limit=traffic_limit,
        connection_link=connection_link,
    )

    return text, sub.plan.value, devices_limit, traffic_limit


# ─── Профиль ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:profile")
async def cb_show_profile(call: CallbackQuery, repo: Repository) -> None:
    text, _, _, _ = await _build_profile_text(repo, call.from_user.id)
    await edit_screen(call, "profile", text, reply_markup=profile_keyboard())
    await call.answer()


@router.message(Command("profile"))
async def cmd_profile(message: Message, repo: Repository) -> None:
    text, _, _, _ = await _build_profile_text(repo, message.from_user.id)
    await send_screen(message, "profile", text, reply_markup=profile_keyboard())

