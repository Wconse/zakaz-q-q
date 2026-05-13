from __future__ import annotations

import logging
from typing import Any

import aiohttp

from config.loader import config

logger = logging.getLogger(__name__)


class CryptoBotClient:
    def __init__(self) -> None:
        cfg = config.payments.cryptobot
        self._token = cfg.token
        self._enabled = cfg.enabled
        network = cfg.network
        if network == "testnet":
            self._base = "https://testnet-pay.crypt.bot/api"
        else:
            self._base = "https://pay.crypt.bot/api"

    @property
    def _headers(self) -> dict:
        return {"Crypto-Pay-API-Token": self._token}

    async def create_invoice(
        self,
        amount_usdt: float,
        description: str,
        payment_id: str,
    ) -> dict | None:
        if not self._enabled:
            return None

        payload = {
            "asset": "USDT",
            "amount": str(amount_usdt),
            "description": description,
            "payload": payment_id,
            "allow_comments": False,
            "allow_anonymous": True,
        }

        try:
            async with aiohttp.ClientSession(headers=self._headers) as session:
                async with session.post(
                    f"{self._base}/createInvoice", json=payload
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        invoice = data["result"]
                        return {
                            "external_id": str(invoice["invoice_id"]),
                            "pay_url": invoice["bot_invoice_url"],
                            "status": invoice["status"],
                        }
                    logger.error("CryptoBot createInvoice failed: %s", data)
                    return None
        except aiohttp.ClientError as e:
            logger.error("CryptoBot request error: %s", e)
            return None

    async def get_invoice(self, invoice_id: str) -> dict | None:
        try:
            async with aiohttp.ClientSession(headers=self._headers) as session:
                async with session.get(
                    f"{self._base}/getInvoices",
                    params={"invoice_ids": invoice_id},
                ) as resp:
                    data = await resp.json()
                    if data.get("ok") and data["result"]["items"]:
                        return data["result"]["items"][0]
                    return None
        except aiohttp.ClientError as e:
            logger.error("CryptoBot getInvoice error: %s", e)
            return None

    async def check_payment_status(self, invoice_id: str) -> str | None:
        """Returns 'paid', 'active', 'expired' or None."""
        data = await self.get_invoice(invoice_id)
        return data.get("status") if data else None


cryptobot = CryptoBotClient()
