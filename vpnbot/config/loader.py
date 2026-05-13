from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        # Try relative to project root
        p = Path(__file__).parent / p.name
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─── Prices ──────────────────────────────────────────────────────────────────

@dataclass
class DaysOption:
    days: int
    price_rub: float
    price_usdt: float


@dataclass
class PlanPrices:
    devices: int
    days_options: list[DaysOption]


@dataclass
class ReferralPrices:
    inviter_bonus_days: int
    invitee_bonus_days: int


@dataclass
class Prices:
    standard: PlanPrices
    extended: PlanPrices
    trial: PlanPrices
    referral: ReferralPrices
    squads: dict[str, list[str]]


def _parse_prices(d: dict) -> Prices:
    def plan(key: str) -> PlanPrices:
        p = d[key]
        opts = [DaysOption(**o) for o in p.get("days_options", [])]
        return PlanPrices(devices=p["devices"], days_options=opts)

    ref = d.get("referral", {})
    trial_d = d.get("trial", {})
    squads = d.get("squads", {})

    return Prices(
        standard=plan("standard"),
        extended=plan("extended"),
        trial=PlanPrices(
            devices=trial_d.get("devices", 3),
            days_options=[],
        ),
        referral=ReferralPrices(
            inviter_bonus_days=ref.get("inviter_bonus_days", 7),
            invitee_bonus_days=ref.get("invitee_bonus_days", 3),
        ),
        squads={k: v or [] for k, v in squads.items()},
    )


# ─── Config ──────────────────────────────────────────────────────────────────

@dataclass
class BotConfig:
    token: str
    admins: list[int]
    username: str


@dataclass
class RemnaConfig:
    base_url: str
    api_token: str


@dataclass
class YuKassaConfig:
    enabled: bool
    shop_id: str
    secret_key: str


@dataclass
class CryptoBotConfig:
    enabled: bool
    token: str
    network: str = "mainnet"


@dataclass
class PaymentsConfig:
    yukassa: YuKassaConfig
    cryptobot: CryptoBotConfig


@dataclass
class LinksConfig:
    channel: str
    channel_id: int
    support: str
    reviews: str = ""


@dataclass
class FeaturesConfig:
    trial_enabled: bool
    trial_days: int
    referral_enabled: bool


@dataclass
class DatabaseConfig:
    url: str


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class SchedulerConfig:
    backup_interval_hours: int
    inactive_delete_days: int
    backup_keep_count: int
    backup_dir: str


@dataclass
class Config:
    bot: BotConfig
    remnawave: RemnaConfig
    payments: PaymentsConfig
    links: LinksConfig
    features: FeaturesConfig
    database: DatabaseConfig
    logging: LoggingConfig
    scheduler: SchedulerConfig


def _parse_config(d: dict) -> Config:
    yk = d["payments"]["yukassa"]
    cb = d["payments"]["cryptobot"]
    sched = d.get("scheduler", {})
    return Config(
        bot=BotConfig(**d["bot"]),
        remnawave=RemnaConfig(**d["remnawave"]),
        payments=PaymentsConfig(
            yukassa=YuKassaConfig(**yk),
            cryptobot=CryptoBotConfig(**cb),
        ),
        links=LinksConfig(**d["links"]),
        features=FeaturesConfig(**d["features"]),
        database=DatabaseConfig(**d["database"]),
        logging=LoggingConfig(**d["logging"]),
        scheduler=SchedulerConfig(
            backup_interval_hours=sched.get("backup_interval_hours", 24),
            inactive_delete_days=sched.get("inactive_delete_days", 3),
            backup_keep_count=sched.get("backup_keep_count", 7),
            backup_dir=sched.get("backup_dir", "backups"),
        ),
    )


# ─── Messages ────────────────────────────────────────────────────────────────

class Messages:
    def __init__(self, d: dict) -> None:
        self._d = d
        self.buttons: dict[str, str] = d.get("buttons", {})
        self.messages: dict[str, str] = d.get("messages", {})
        self.plans: dict[str, str] = d.get("plans", {})


# ─── Globals ─────────────────────────────────────────────────────────────────

_BASE = Path(__file__).parent

config: Config = _parse_config(_load(str(_BASE / "config.yaml")))
prices: Prices = _parse_prices(_load(str(_BASE / "prices.yaml")))
messages: Messages = Messages(_load(str(_BASE / "messages.yaml")))
