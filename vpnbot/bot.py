from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands

from app.bot.handlers import admin_panel, admin_pricing, broadcast, payment, profile, referral_promo, start
from app.bot.middlewares.database import DatabaseMiddleware
from app.database.engine import create_tables
from app.scheduler import run_scheduler
from config.loader import config
from config.logger import setup_logging

logger = logging.getLogger(__name__)


BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="menu", description="Открыть меню"),
    BotCommand(command="profile", description="Мой профиль"),
    BotCommand(command="plans", description="Тарифы и подключение"),
    BotCommand(command="promo", description="Ввести промокод"),
    BotCommand(command="referral", description="Реферальная программа"),
    BotCommand(command="info", description="Информация / каналы"),
    BotCommand(command="support", description="Поддержка"),
    BotCommand(command="admin", description="Админ-панель"),
]


async def _setup_bot_ui(bot: Bot) -> None:
    """Зарегистрировать команды и поставить кнопку-меню (MenuButton).
    Безопасно к повторным запускам."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Bot commands and menu button registered")
    except Exception as e:
        logger.warning("Failed to set bot UI: %s", e)


async def main() -> None:
    setup_logging()
    logger.info("Starting VPN bot...")

    # Create DB tables
    await create_tables()

    bot = Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())

    # Routers (order matters — admin router first for priority)
    dp.include_router(start.router)
    dp.include_router(payment.router)
    dp.include_router(profile.router)
    dp.include_router(referral_promo.router)
    dp.include_router(admin_panel.router)
    dp.include_router(admin_pricing.router)
    dp.include_router(broadcast.router)

    # Bot commands & menu button
    await _setup_bot_ui(bot)

    # Start scheduler as background task
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler_task.cancel()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
