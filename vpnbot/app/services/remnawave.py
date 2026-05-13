from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from remnawave import RemnawaveSDK
from remnawave.models import CreateUserRequestDto, UpdateUserRequestDto, UserResponseDto

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


def _dump_model(obj: Any) -> Any:
    """Pydantic v2/v1 safe dump."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj


def _parse_dt_utc(value: str | datetime) -> datetime:
    """
    Remnawave SDK ожидает datetime (см. CreateUserRequestDto.expire_at / UpdateUserRequestDto.expire_at).
    В проекте сейчас везде прокидывается ISO-строка вида 'YYYY-MM-DDTHH:MM:SSZ' — конвертим.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = value.strip()
        # 'Z' -> '+00:00' чтобы datetime.fromisoformat нормально распарсил
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # fallback на самый частый формат из вашего кода
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_uuid_list(value: Any) -> list[str]:
    """
    prices.squads.<plan> у вас хранится как list[...] (см. prices.yaml).
    В Remnawave SDK это хорошо ложится на active_internal_squads: List[UUID].
    """
    if value is None:
        return []

    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []

    if isinstance(value, Sequence):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                item = item.strip()
                if item:
                    out.append(item)
            else:
                # На всякий случай (если кто-то положит UUID-объекты)
                out.append(str(item))
        return out

    # на всякий случай
    return [str(value)]


def _dto_to_remna_user(dto: UserResponseDto) -> RemnaUser:
    """Convert SDK UserResponseDto to our internal RemnaUser dataclass."""
    sub_url = getattr(dto, "subscription_url", None)

    # В актуальном UserResponseDto нет online_count; оставляем мягко (0 если поля нет)
    devices_count = (
        getattr(dto, "online_count", None)
        or getattr(dto, "onlineConnectionsCount", None)
        or 0
    )

    hwid_device_limit = getattr(dto, "hwid_device_limit", None)

    expire_at_raw = getattr(dto, "expire_at", None)
    expire_at: str | None = None
    if expire_at_raw is not None:
        if hasattr(expire_at_raw, "strftime"):
            expire_at = expire_at_raw.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            expire_at = str(expire_at_raw)

    return RemnaUser(
        uuid=str(getattr(dto, "uuid")),
        username=getattr(dto, "username", "") or "",
        subscription_url=sub_url,
        devices_count=int(devices_count or 0),
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
            users_api = self._sdk.users
            if hasattr(users_api, "get_user_by_uuid"):
                dto: UserResponseDto = await users_api.get_user_by_uuid(uuid)
            else:
                # fallback на случай старого контракта
                dto = await users_api.get_user(uuid)  # type: ignore[attr-defined]
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
        description = f"@{username}" if username else None

        plan_squads_raw = getattr(prices, "squads", {}).get(plan, [])
        active_internal_squads = _normalize_uuid_list(plan_squads_raw)

        try:
            req = CreateUserRequestDto(
                username=tg_name,
                description=description,
                telegram_id=telegram_id,
                expire_at=_parse_dt_utc(expire_at),
                hwid_device_limit=hwid_device_limit,
                active_internal_squads=active_internal_squads or None,
            )
            dto = await self._sdk.users.create_user(req)
            logger.info("Remnawave user created: %s (uuid=%s, sub_url=%s)", tg_name, dto.uuid, getattr(dto, "subscription_url", None))
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.error("create_user %s failed: %s | type=%s | details=%s", tg_name, e, type(e).__name__, repr(e))
            return None

    async def update_user(
        self,
        uuid: str,
        expire_at: str | None = None,
        hwid_device_limit: int | None = None,
        description: str | None = None,
        plan: str | None = None,
    ) -> RemnaUser | None:
        payload: dict[str, Any] = {"uuid": uuid}

        if expire_at is not None:
            payload["expire_at"] = _parse_dt_utc(expire_at)
        if hwid_device_limit is not None:
            payload["hwid_device_limit"] = hwid_device_limit
        if description is not None:
            payload["description"] = description

        if plan is not None:
            plan_squads_raw = getattr(prices, "squads", {}).get(plan, [])
            active_internal_squads = _normalize_uuid_list(plan_squads_raw)
            payload["active_internal_squads"] = active_internal_squads or None

        if len(payload) == 1:
            return None

        try:
            req = UpdateUserRequestDto(**payload)
            dto = await self._sdk.users.update_user(req)
            logger.info("Remnawave user updated: %s (sub_url=%s)", uuid, getattr(dto, "subscription_url", None))
            return _dto_to_remna_user(dto)
        except Exception as e:
            logger.error("update_user(%s) failed: %s | type=%s | details=%s", uuid, e, type(e).__name__, repr(e))
            return None

    async def delete_user(self, uuid: str) -> bool:
        try:
            res = await self._sdk.users.delete_user(uuid)
            # DeleteUserResponseDto.is_deleted (alias isDeleted)
            is_deleted = getattr(res, "is_deleted", None)
            return bool(is_deleted) if is_deleted is not None else True
        except Exception as e:
            logger.error("delete_user(%s) failed: %s", uuid, e)
            return False

    async def get_subscription_url(self, uuid: str) -> str | None:
        user = await self.get_user_by_uuid(uuid)
        return user.subscription_url if user else None

    async def list_all_users(self) -> list[dict] | None:
        """
        Скачать список всех пользователей панели для бэкапа.
        Возвращает list[dict] или None если SDK/API недоступны.
        """
        try:
            users_api = self._sdk.users

            # Нормальный путь для SDK 2.x
            method = getattr(users_api, "get_all_users", None)
            if method is not None:
                start = 0
                size = 1000
                acc: list[Any] = []

                while True:
                    resp = await method(start=start, size=size)
                    # resp.users + resp.total
                    batch = getattr(resp, "users", None)
                    total = getattr(resp, "total", None)

                    if batch is None:
                        # странный контракт — просто дампнем resp как есть
                        dumped = _dump_model(resp)
                        if isinstance(dumped, dict):
                            items = dumped.get("users") or dumped.get("items")
                            if isinstance(items, list):
                                return [dict(_dump_model(x)) for x in items]
                        return [dict(dumped)] if isinstance(dumped, dict) else None

                    batch_list = list(batch)
                    acc.extend(batch_list)

                    if not batch_list:
                        break
                    if len(batch_list) < size:
                        break
                    if total is not None and len(acc) >= int(total):
                        break

                    start += size

                return [dict(_dump_model(u)) for u in acc]

            # fallback (если в каком-то контракте метод называется иначе)
            for method_name in ("get_users", "list_users"):
                m = getattr(users_api, method_name, None)
                if m is None:
                    continue
                result = await m()
                if isinstance(result, list):
                    return [dict(_dump_model(x)) for x in result]
                dumped = _dump_model(result)
                if isinstance(dumped, dict):
                    items = dumped.get("users") or dumped.get("items")
                    if isinstance(items, list):
                        return [dict(_dump_model(x)) for x in items]
                    return [dict(dumped)]
                return None

            logger.warning("list_all_users: no compatible SDK method found")
            return None

        except Exception as e:
            logger.warning("list_all_users failed: %s", e)
            return None


remna = RemnaWaveClient()