from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import AdminFilter
from app.database.models import BroadcastLog
from app.database.repository import Repository
from config.loader import messages

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

msg = messages.messages


class BroadcastStates(StatesGroup):
    waiting_message = State()
    waiting_user_id = State()
    waiting_personal_message = State()
    _target_user_id = State()


# ─────────────────────────────────────────
# Mass broadcast
# ─────────────────────────────────────────

@router.callback_query(F.data == "admin:broadcast:mass")
async def cb_broadcast_mass_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting_message)
    await call.message.answer(msg["admin_ask_broadcast_text"])
    await call.answer()


@router.message(BroadcastStates.waiting_message)
async def handle_broadcast_mass(message: Message, state: FSMContext, repo: Repository, bot: Bot) -> None:
    await state.clear()
    text = message.html_text

    users = await repo.users.get_all()
    sent = 0
    for user in users:
        if user.blocked_bot_at:
            continue
        try:
            await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)  # flood prevention
        except TelegramForbiddenError:
            await repo.users.mark_blocked(user.telegram_id)
        except Exception as e:
            logger.warning("Broadcast failed for %d: %s", user.telegram_id, e)

    await repo.commit()

    log = BroadcastLog(
        admin_id=message.from_user.id,
        message_text=text,
        sent_count=sent,
    )
    repo.session.add(log)
    await repo.commit()

    await message.answer(msg["admin_broadcast_done"].format(count=sent))


# ─────────────────────────────────────────
# Personal message
# ─────────────────────────────────────────

@router.callback_query(F.data == "admin:broadcast:personal")
async def cb_broadcast_personal_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting_user_id)
    await call.message.answer(msg["admin_ask_user_id"])
    await call.answer()


@router.message(BroadcastStates.waiting_user_id)
async def handle_personal_target(message: Message, state: FSMContext, repo: Repository) -> None:
    query = message.text.strip()
    user = None
    if query.startswith("@"):
        user = await repo.users.get_by_username(query)
    else:
        try:
            user = await repo.users.get_by_telegram_id(int(query))
        except ValueError:
            user = await repo.users.get_by_username(query)

    if not user:
        await message.answer(msg["admin_no_user"])
        await state.clear()
        return

    await state.update_data(target_user_id=user.telegram_id)
    await state.set_state(BroadcastStates.waiting_personal_message)
    await message.answer(
        msg["admin_ask_personal_message"].format(user_id=user.telegram_id)
    )


@router.message(BroadcastStates.waiting_personal_message)
async def handle_personal_message(message: Message, state: FSMContext, repo: Repository, bot: Bot) -> None:
    data = await state.get_data()
    target_id = data.get("target_user_id")
    await state.clear()

    text = message.html_text
    try:
        await bot.send_message(target_id, text, parse_mode="HTML")

        log = BroadcastLog(
            admin_id=message.from_user.id,
            message_text=text,
            sent_count=1,
            target_user_id=target_id,
        )
        repo.session.add(log)
        await repo.commit()
        await message.answer(f"✅ Сообщение отправлено пользователю <code>{target_id}</code>", parse_mode="HTML")
    except TelegramForbiddenError:
        await repo.users.mark_blocked(target_id)
        await repo.commit()
        await message.answer(f"❌ Пользователь заблокировал бота")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")


# ─────────────────────────────────────────
# Personal message from user actions
# ─────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:user:message:"))
async def cb_send_to_user_prompt(call: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(call.data.split(":")[-1])
    await state.update_data(target_user_id=tg_id)
    await state.set_state(BroadcastStates.waiting_personal_message)
    await call.message.answer(msg["admin_ask_personal_message"].format(user_id=tg_id))
    await call.answer()
