"""Helpers for sending and editing 'screens' — single bot messages
that consist of (optional) image + caption + inline keyboard.

Каждая «сцена» в боте — это одно сообщение, которое мы редактируем
при переходах через inline-кнопки. Если в каталоге `assets/` есть файл
с подходящим именем — он подкладывается как фото; иначе шлём только текст.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
_EXT_PRIORITY = (".jpg", ".jpeg", ".png")

# Telegram caption hard-limit
_CAPTION_MAX = 1024


def screen_image_path(screen: str) -> Path | None:
    """Return path to the image for a given screen name, or None if absent."""
    for ext in _EXT_PRIORITY:
        p = ASSETS_DIR / f"{screen}{ext}"
        if p.exists():
            return p
    return None


def _fits_caption(text: str) -> bool:
    """Безопасно ли поместить текст в caption фото (лимит Telegram — 1024).
    Если нет — вызывающий код должен отправлять text-only сообщение,
    чтобы избежать обрезания HTML-тегов и UTF-8 в произвольной позиции."""
    return len(text) <= _CAPTION_MAX


async def send_screen(
    target: Message | CallbackQuery,
    screen: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
) -> Message:
    """Send a new screen message: photo + caption when и текст влезает в 1024 символа,
    иначе — обычный text message. Файл картинки берётся из `assets/`; если его нет,
    fallback — text."""
    message = target.message if isinstance(target, CallbackQuery) else target
    image = screen_image_path(screen)

    if image is not None and _fits_caption(text):
        return await message.answer_photo(
            photo=FSInputFile(image),
            caption=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def edit_screen(
    call: CallbackQuery,
    screen: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
) -> None:
    """Edit the screen of an existing message (the one carrying the inline kb).

    Behaviour:
    - source has photo + target has photo: edit_media (replaces the photo) or edit_caption (same photo).
    - source has photo + target has no photo: delete and re-send (Telegram cannot
      remove media from an already-photo message).
    - source is text-only + target has photo: delete and re-send a photo message.
    - source is text-only + target is text-only: edit_text.
    """
    message = call.message
    target_image = screen_image_path(screen)
    source_has_photo = bool(message.photo)
    target_uses_photo = target_image is not None and _fits_caption(text)

    try:
        # Both sides — photo with fitting caption: swap media + caption.
        if source_has_photo and target_uses_photo:
            try:
                await message.edit_media(
                    media=InputMediaPhoto(
                        media=FSInputFile(target_image),
                        caption=text,
                        parse_mode=parse_mode,
                    ),
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return
                # Telegram иногда отвечает «not modified» без явной фразы — на тех же
                # путях обычно достаточно обновить только caption.
                if "media" in err and "modified" in err:
                    try:
                        await message.edit_caption(
                            caption=text, parse_mode=parse_mode, reply_markup=reply_markup
                        )
                        return
                    except TelegramBadRequest:
                        pass
                raise
            return

        # Both sides — text only.
        if not source_has_photo and not target_uses_photo:
            await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return

        # Type mismatch — пересоздаём сообщение (delete + re-send).
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        await send_screen(call, screen, text, reply_markup, parse_mode)

    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.warning("edit_screen failed for screen=%s: %s; re-sending", screen, e)
        try:
            await message.delete()
        except Exception:
            pass
        await send_screen(call, screen, text, reply_markup, parse_mode)
