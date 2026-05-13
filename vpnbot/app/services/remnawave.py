from __future__ import annotations

import logging
from dataclasses import dataclass

from remnawave import RemnawaveSDK
from remnawave.models import UserResponseDto, CreateUserRequestDto, UpdateUserRequestDto

from config.loader import config, prices

logger = logging.getLogger(__name__)


@dataclass
class RemnaUser:
    uuid: str
    username: str
    subscription_url: str | None
    devices_count: int
    expire_at: str | None
    hwid_device_limit: int | None


def _dto_to_remna_user(dto: UserResponseDto) -> RemnaUser:
    """Convert SDK UserResponseDto to our internal RemnaUser dataclass."""
    sub_url = getattr(dto, "subscription_url", None)
    devices_count = getattr(dto, "online_count", 0) or 0
    hwid_device_limit = getattr(dto, "hwid_device_limit", None)

    expire_at_raw = getattr(dto, "expire_at", None)
    expire_at: str | None = None
    if expire_at_raw is not None:
        if hasattr(expire_at_raw, "strftime"):
            expire_at = expire_at_raw.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            expire_at = str(expire_at_raw)

    return RemnaUser(
        uuid=str(dto.uuid),
        username=dto.username or "",
        subscription_url=sub_url,
        devices_count=devices_count,
        expire_at=expire_at,
        hwid_device_limit=hwid_device_limit,
    )


class RemnaWaveClient:
    """Wrapper around the official Remnawave Python SDK (pip install remnawave)."""

    def __init__(self) -> None:
        self._sdk = RemnawaveSDK(
            base_url=config.remnawave.base_url,
            token=config.remnawave.api_token,
        )

    # ── Users ──────────────────────────────────────────────────────────────

    async def get_user_by_uuid(self, uuid: str) -> RemnaUser | None:
        try:
            dto: UserResponseDto = await self._sdk.users.get_user(uuid)
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.warning("get_user_by_uuid(%s) failed: %s", uuid, e)
            return None

    async def get_user_by_username(self, username: str) -> RemnaUser | None:
        try:
            dto: UserResponseDto = await self._sdk.users.get_user_by_username(username)
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.warning("get_user_by_username(%s) failed: %s", username, e)
            return None

    async def create_user(
        self,
        telegram_id: int,
        username: str | None,
        plan: str,
        expire_at: str,
        hwid_device_limit: int,
    ) -> RemnaUser | None:
        tg_name = f"TG_{telegram_id}"
        description = f"@{username}" if username else ""

        # active_user_inbounds: list of inbound UUIDs to connect the user to.
        # Configured per-plan in prices.yaml under the "squads" key.
        active_inbounds: list[str] = prices.squads.get(plan, [])

        try:
            req = CreateUserRequestDto(
                username=tg_name,
                description=description,
                expire_at=expire_at,
                # Correct API field for per-user HWID device limit
                hwid_device_limit=hwid_device_limit,
                # Correct API field for assigning inbounds/squads
                active_user_inbounds=active_inbounds if active_inbounds else None,
            )
            dto: UserResponseDto = await self._sdk.users.create_user(req)
            logger.info("Remnawave user created: %s (uuid=%s)", tg_name, dto.uuid)
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.error("create_user TG_%d failed: %s", telegram_id, e)
            return None

    async def update_user(
        self,
        uuid: str,
        expire_at: str | None = None,
        hwid_device_limit: int | None = None,
        description: str | None = None,
    ) -> RemnaUser | None:
        kwargs: dict = {}
        if expire_at is not None:
            kwargs["expire_at"] = expire_at
        if hwid_device_limit is not None:
            # Correct API field name — not "devices_limit"
            kwargs["hwid_device_limit"] = hwid_device_limit
        if description is not None:
            kwargs["description"] = description

        if not kwargs:
            return None

        try:
            req = UpdateUserRequestDto(**kwargs)
            dto: UserResponseDto = await self._sdk.users.update_user(uuid, req)
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.error("update_user(%s) failed: %s", uuid, e)
            return None

    async def delete_user(self, uuid: str) -> bool:
        try:
            await self._sdk.users.delete_user(uuid)
            return True
        except Exception as e:
            logger.error("delete_user(%s) failed: %s", uuid, e)
            return False

    async def get_subscription_url(self, uuid: str) -> str | None:
        user = await self.get_user_by_uuid(uuid)
        return user.subscription_url if user else None

    async def list_all_users(self) -> list[dict] | None:
        """Скачать список всех пользователей панели для бэкапа.

        Используется ежедневным шедулером бэкапа. Возвращает list[dict]
        (плоский снимок users) или None если SDK/API недоступны.
        Метод намеренно мягкий — любые ошибки логируются и возвращается None,
        чтобы scheduler мог записать error-stub.
        """
        try:
            users_api = self._sdk.users
            # SDK 2.x экспортирует один из этих методов в зависимости от версии.
            for method_name in ("get_all_users", "get_users", "list_users"):
                method = getattr(users_api, method_name, None)
                if method is None:
                    continue
                result = await method()
                # Нормализуем разные формы ответа (list / Page-like / dict с items)
                if hasattr(result, "model_dump"):
                    dumped = result.model_dump()
                    items = dumped.get("users") or dumped.get("items") or dumped
                    return items if isinstance(items, list) else [dumped]
                if isinstance(result, list):
                    return [
                        item.model_dump() if hasattr(item, "model_dump") else dict(item)
                        for item in result
                    ]
                if isinstance(result, dict):
                    items = result.get("users") or result.get("items") or [result]
                    return items
            logger.warning("list_all_users: no compatible SDK method found")
            return None
        except Exception as e:
            logger.warning("list_all_users failed: %s", e)
            return None


remna = RemnaWaveClient()
