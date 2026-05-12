from __future__ import annotations

import logging
import uuid
from typing import Any

import aiohttp

from config.loader import config

logger = logging.getLogger(__name__)

_API = "https://api.yookassa.ru/v2"


class YuKassaClient:
    def __init__(self) -> None:
        cfg = config.payments.yukassa
        self._shop_id = cfg.shop_id
        self._secret = cfg.secret_key
        self._enabled = cfg.enabled

    async def create_payment(
        self,
        amount: float,
        description: str,
        payment_id: str,
        metadata: dict | None = None,
    ) -> dict | None:
        if not self._enabled:
            return None

        idempotency_key = str(uuid.uuid4())
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/your_bot",  # Will be overridden by config ideally
            },
            "description": description,
            "metadata": {"payment_id": payment_id, **(metadata or {})},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_API}/payments",
                    json=payload,
                    auth=aiohttp.BasicAuth(self._shop_id, self._secret),
                    headers={"Idempotence-Key": idempotency_key},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "external_id": data["id"],
                            "confirmation_url": data["confirmation"]["confirmation_url"],
                            "status": data["status"],
                        }
                    body = await resp.text()
                    logger.error("YuKassa create_payment failed %d: %s", resp.status, body)
                    return None
        except aiohttp.ClientError as e:
            logger.error("YuKassa request error: %s", e)
            return None

    async def get_payment(self, external_id: str) -> dict | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_API}/payments/{external_id}",
                    auth=aiohttp.BasicAuth(self._shop_id, self._secret),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
        except aiohttp.ClientError as e:
            logger.error("YuKassa get_payment error: %s", e)
            return None

    async def check_payment_status(self, external_id: str) -> str | None:
        """Returns 'succeeded', 'pending', 'canceled' or None."""
        data = await self.get_payment(external_id)
        return data.get("status") if data else None


yukassa = YuKassaClient()
