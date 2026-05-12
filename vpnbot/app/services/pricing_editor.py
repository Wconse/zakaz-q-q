"""Editor for `config/prices.yaml` — add/remove duration options for plans.

Используется админ-панелью для управления списком `days_options` тарифов
без перезапуска бота: после правки YAML-файл перечитывается.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from config import loader as config_loader
from config.loader import DaysOption

logger = logging.getLogger(__name__)

_PRICES_PATH = Path(config_loader.__file__).parent / "prices.yaml"


def _read() -> dict:
    with open(_PRICES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write(data: dict) -> None:
    with open(_PRICES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def reload_prices() -> None:
    """Перечитать prices.yaml и обновить days_options существующего
    объекта `config.loader.prices` (мутируем in-place, чтобы импорты
    `from config.loader import prices` в хендлерах продолжали работать)."""
    data = _read()
    cur = config_loader.prices
    for plan_name in ("standard", "extended"):
        new_options = [DaysOption(**o) for o in data.get(plan_name, {}).get("days_options", [])]
        getattr(cur, plan_name).days_options[:] = new_options


def has_days(plan: str, days: int) -> bool:
    data = _read()
    plan_data = data.get(plan, {})
    return any(o.get("days") == days for o in plan_data.get("days_options", []))


def add_days_option(plan: str, days: int, price_rub: float, price_usdt: float) -> bool:
    """Добавить вариант длительности. False — если уже существует."""
    if plan not in ("standard", "extended"):
        raise ValueError(f"Unknown plan: {plan}")

    data = _read()
    plan_data = data.setdefault(plan, {})
    options: list = plan_data.setdefault("days_options", [])

    for opt in options:
        if opt.get("days") == days:
            return False

    options.append({"days": int(days), "price_rub": float(price_rub), "price_usdt": float(price_usdt)})
    options.sort(key=lambda o: o["days"])
    _write(data)
    reload_prices()
    logger.info("Added pricing option: plan=%s days=%d rub=%s usdt=%s", plan, days, price_rub, price_usdt)
    return True


def remove_days_option(plan: str, days: int) -> bool:
    """Удалить вариант длительности. False — если не найден."""
    if plan not in ("standard", "extended"):
        raise ValueError(f"Unknown plan: {plan}")

    data = _read()
    options: list = data.get(plan, {}).get("days_options", [])
    new_options = [o for o in options if o.get("days") != days]
    if len(new_options) == len(options):
        return False

    data[plan]["days_options"] = new_options
    _write(data)
    reload_prices()
    logger.info("Removed pricing option: plan=%s days=%d", plan, days)
    return True
