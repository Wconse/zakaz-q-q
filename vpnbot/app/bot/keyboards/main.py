from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.loader import config, messages

btn = messages.buttons


# ─── Главное меню (inline) ────────────────────────────────────────────────────
def main_menu_keyboard(is_admin: bool = False, trial_used: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # Основные кнопки
    rows.append([InlineKeyboardButton(text="🆓 Пробный период", callback_data="plan:trial")])
    rows.append([InlineKeyboardButton(text=btn["subscribe"], callback_data="menu:subscribe")])
    rows.append([InlineKeyboardButton(text=btn["profile"], callback_data="menu:profile")])
    rows.append([InlineKeyboardButton(text=btn["support"], url=config.links.support)])
    rows.append([InlineKeyboardButton(text=btn["channel"], url=config.links.channel)])

    if is_admin:
        rows.append([InlineKeyboardButton(text=btn["admin_panel"], callback_data="menu:admin")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=btn["back"], callback_data="menu:back")]]
    )


# ─── Кнопка продления (для напоминаний scheduler) ─────────────────────────────
def renew_keyboard() -> InlineKeyboardMarkup:
    """
    Эту функцию импортирует scheduler.py:
    from app.bot.keyboards.main import renew_keyboard

    Делаем простую клавиатуру "Продлить" -> menu:renew.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["renew"], callback_data="menu:renew")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


# ─── Профиль ──────────────────────────────────────────────────────────────────
def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["renew"], callback_data="menu:renew")],
            [InlineKeyboardButton(text=btn["change_plan"], callback_data="menu:change_plan")],
            [InlineKeyboardButton(text=btn["referral"], callback_data="menu:referral")],
            [InlineKeyboardButton(text=btn["promo"], callback_data="menu:promo")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


# ─── Выбор плана ──────────────────────────────────────────────────────────────
def plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💠 Стандартная", callback_data="plan:standard")],
            [InlineKeyboardButton(text="💎 Расширенная", callback_data="plan:extended")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


# ─── Выбор периода ────────────────────────────────────────────────────────────
def period_keyboard(plan: str, periods: list) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for p in periods:
        label = f"🗓 {p.days} дней – {p.price_rub:.0f}₽"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"period:{plan}:{p.days}:{p.price_rub}:{p.price_usdt}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text=btn["back"], callback_data="back:plans")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Выбор метода оплаты ──────────────────────────────────────────────────────
def payment_method_keyboard(plan: str, days: int, price_rub: float, price_usdt: float) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if config.payments.yukassa.enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn["pay_yukassa"],
                    callback_data=f"pay:yukassa:{plan}:{days}:{price_rub}",
                )
            ]
        )

    if config.payments.cryptobot.enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn["pay_crypto"],
                    callback_data=f"pay:crypto:{plan}:{days}:{price_usdt}",
                )
            ]
        )

    rows.append([InlineKeyboardButton(text=btn["back"], callback_data=f"back:period:{plan}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Trial ────────────────────────────────────────────────────────────────────
def trial_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☑️ Подписаться", url=channel_url)],
            [InlineKeyboardButton(text="♻️ Проверить подписку", callback_data="trial:check")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


# ─── Ссылка оплаты ────────────────────────────────────────────────────────────
def pay_url_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=url)],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


def promo_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="menu:back")]]
    )


# ─── Продление: выбор периода ─────────────────────────────────────────────────
def renew_period_keyboard(plan: str, periods: list) -> InlineKeyboardMarkup:
    """Клавиатура для выбора периода продления действующей подписки."""
    buttons: list[list[InlineKeyboardButton]] = []

    for p in periods:
        label = f"🔄 Продлить на {p.days} дней"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"renew:{plan}:{p.days}:{p.price_rub}:{p.price_usdt}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text=btn["back"], callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)