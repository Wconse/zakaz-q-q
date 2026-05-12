from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardRemove,
)

from app.bot.keyboards.main import main_menu_keyboard
from app.bot.screens import edit_screen, send_screen
from app.database.repository import Repository
from config.loader import config, messages, prices

logger = logging.getLogger(__name__)
router = Router()

msg = messages.messages


def _is_admin(user_id: int) -> bool:
    return user_id in config.bot.admins


async def _send_main_menu(message: Message, name: str, intro: str, trial_used: bool = False) -> None:
    try:
        helper = await message.answer("…", reply_markup=ReplyKeyboardRemove())
        await helper.delete()
    except Exception:
        pass

    text = intro.format(name=name) if "{name}" in intro else intro
    await send_screen(
        message,
        screen="main",
        text=text,
        reply_markup=main_menu_keyboard(
            is_admin=_is_admin(message.from_user.id),
            trial_used=trial_used,
        ),
    )


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repository, command: CommandObject) -> None:
    tg_user = message.from_user
    referred_by: int | None = None

    if command.args and command.args.startswith("ref_"):
        try:
            ref_id = int(command.args.split("_", 1)[1])
            if ref_id != tg_user.id:
                referrer = await repo.users.get_by_telegram_id(ref_id)
                if referrer:
                    referred_by = ref_id
        except (ValueError, IndexError):
            pass

    user, created = await repo.users.get_or_create(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        referred_by=referred_by,
    )
    await repo.commit()

    name = tg_user.first_name or tg_user.username or "друг"

    if referred_by and created:
        bonus = prices.referral.invitee_bonus_days
        intro = msg["start_ref"].format(name=name, bonus_days=bonus)
    else:
        intro = msg["start"].format(name=name)

    await _send_main_menu(message, name, intro, trial_used=user.trial_used)


# ─── /menu ───────────────────────────────────────────────────────────────────

@router.message(Command("menu"))
async def cmd_menu(message: Message, repo: Repository) -> None:
    name = message.from_user.first_name or "друг"
    intro = msg["start"].format(name=name)
    user = await repo.users.get_by_telegram_id(message.from_user.id)
    trial_used = user.trial_used if user else False
    await _send_main_menu(message, name, intro, trial_used=trial_used)


# ─── menu:back ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "menu:back")
async def cb_back_main(call: CallbackQuery, repo: Repository) -> None:
    name = call.from_user.first_name or "друг"
    intro = msg["start"].format(name=name)
    user = await repo.users.get_by_telegram_id(call.from_user.id)
    trial_used = user.trial_used if user else False
    await edit_screen(
        call,
        screen="main",
        text=intro,
        reply_markup=main_menu_keyboard(
            is_admin=_is_admin(call.from_user.id),
            trial_used=trial_used,
        ),
    )
    await call.answer()