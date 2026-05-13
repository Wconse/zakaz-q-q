from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from config.loader import config


class AdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        return user.id in config.bot.admins
