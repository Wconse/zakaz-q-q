"""Admin pricing editor — управление длительностями тарифов через бот.

Поток:
    menu:admin_pricing → выбор тарифа (standard/extended)
    admin:price:list:<plan> → список существующих периодов + добавить/удалить
    admin:price:add:<plan> → FSM: дни → цена RUB → цена USDT
    admin:price:del:<plan>:<days> → удаление
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.filters.admin import AdminFilter
from app.bot.keyboards.admin import (
    admin_pricing_keyboard,
    admin_pricing_plan_keyboard,
)
from app.bot.screens import edit_screen
from app.services import pricing_editor
from config import loader as config_loader
from config.loader import messages

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

msg = messages.messages

PLAN_LABELS = {"standard": "Стандартный", "extended": "Расширенный"}


class PricingStates(StatesGroup):
    add_days = State()
    add_rub = State()
    add_usdt = State()


# ─── Меню «Тарифы» ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:admin_pricing")
async def cb_admin_pricing(call: CallbackQuery) -> None:
    await edit_screen(
        call,
        "admin_pricing",
        msg["admin_pricing_menu"],
        reply_markup=admin_pricing_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admin:price:list:"))
async def cb_admin_price_list(call: CallbackQuery) -> None:
    plan = call.data.split(":")[-1]
    if plan not in PLAN_LABELS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    plan_prices = getattr(config_loader.prices, plan)
    text = msg["admin_pricing_plan"].format(plan=PLAN_LABELS[plan])
    await edit_screen(
        call,
        "admin_pricing",
        text,
        reply_markup=admin_pricing_plan_keyboard(plan, plan_prices.days_options),
    )
    await call.answer()


# ─── Удаление периода ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:price:del:"))
async def cb_admin_price_del(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    plan = parts[3]
    try:
        days = int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Неверные данные", show_alert=True)
        return

    if plan not in PLAN_LABELS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    ok = pricing_editor.remove_days_option(plan, days)
    if not ok:
        await call.answer(msg["admin_pricing_not_found"], show_alert=True)
        return

    plan_prices = getattr(config_loader.prices, plan)
    await edit_screen(
        call,
        "admin_pricing",
        msg["admin_pricing_plan"].format(plan=PLAN_LABELS[plan])
        + f"\n\n{msg['admin_pricing_deleted'].format(days=days, plan=PLAN_LABELS[plan])}",
        reply_markup=admin_pricing_plan_keyboard(plan, plan_prices.days_options),
    )
    await call.answer("Удалено")


# ─── Добавление периода (FSM) ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:price:add:"))
async def cb_admin_price_add_start(call: CallbackQuery, state: FSMContext) -> None:
    plan = call.data.split(":")[-1]
    if plan not in PLAN_LABELS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    await state.update_data(pricing_plan=plan)
    await state.set_state(PricingStates.add_days)
    await call.message.answer(msg["admin_pricing_ask_days"], parse_mode="HTML")
    await call.answer()


@router.message(PricingStates.add_days)
async def handle_add_days(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число больше 0.")
        return

    data = await state.get_data()
    plan = data["pricing_plan"]
    if pricing_editor.has_days(plan, days):
        await state.clear()
        await message.answer(msg["admin_pricing_exists"].format(days=days), parse_mode="HTML")
        return

    await state.update_data(pricing_days=days)
    await state.set_state(PricingStates.add_rub)
    await message.answer(msg["admin_pricing_ask_rub"], parse_mode="HTML")


@router.message(PricingStates.add_rub)
async def handle_add_rub(message: Message, state: FSMContext) -> None:
    try:
        rub = float(message.text.strip().replace(",", "."))
        if rub < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число (можно с точкой).")
        return

    await state.update_data(pricing_rub=rub)
    await state.set_state(PricingStates.add_usdt)
    await message.answer(msg["admin_pricing_ask_usdt"], parse_mode="HTML")


@router.message(PricingStates.add_usdt)
async def handle_add_usdt(message: Message, state: FSMContext) -> None:
    try:
        usdt = float(message.text.strip().replace(",", "."))
        if usdt < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число (можно с точкой).")
        return

    data = await state.get_data()
    plan = data["pricing_plan"]
    days = int(data["pricing_days"])
    rub = float(data["pricing_rub"])
    await state.clear()

    added = pricing_editor.add_days_option(plan, days, rub, usdt)
    if added:
        await message.answer(
            msg["admin_pricing_added"].format(days=days, plan=PLAN_LABELS[plan]),
            parse_mode="HTML",
        )
    else:
        await message.answer(msg["admin_pricing_exists"].format(days=days), parse_mode="HTML")
