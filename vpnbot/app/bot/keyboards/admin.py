from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.loader import messages

btn = messages.buttons


# ─── Главное меню админки (теперь inline) ────────────────────────────────────

def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["admin_users"], callback_data="menu:admin_users")],
            [InlineKeyboardButton(text=btn["admin_promo"], callback_data="menu:admin_promo")],
            [InlineKeyboardButton(text=btn["admin_broadcast"], callback_data="menu:admin_broadcast")],
            [InlineKeyboardButton(text=btn["admin_pricing"], callback_data="menu:admin_pricing")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:back")],
        ]
    )


def admin_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["admin_all_users"], callback_data="admin:users:all")],
            [InlineKeyboardButton(text=btn["admin_new_users"], callback_data="admin:users:new")],
            [InlineKeyboardButton(text=btn["admin_blocked"], callback_data="admin:users:blocked")],
            [InlineKeyboardButton(text=btn["admin_find_user"], callback_data="admin:users:find")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:admin")],
        ]
    )


def admin_user_actions_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin:user:grant:{telegram_id}")],
            [InlineKeyboardButton(text="➕ Добавить дни", callback_data=f"admin:user:days:{telegram_id}")],
            [InlineKeyboardButton(text="📱 Изменить устройства", callback_data=f"admin:user:devices:{telegram_id}")],
            [InlineKeyboardButton(text="📈 Лимит трафика", callback_data=f"admin:user:traffic:{telegram_id}")],
            [InlineKeyboardButton(text="🎁 Пробный период", callback_data=f"admin:user:trial:{telegram_id}")],
            [InlineKeyboardButton(text="👥 Приглашенные", callback_data=f"admin:user:referrals:{telegram_id}")],
            [InlineKeyboardButton(text="🎫 Промокоды", callback_data=f"admin:user:promos:{telegram_id}")],
            [InlineKeyboardButton(text="✉️ Написать", callback_data=f"admin:user:message:{telegram_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:user:delete:{telegram_id}")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:admin_users")],
        ]
    )


def admin_grant_plan_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """Выбор типа подписки для выдачи администратором."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👉 Пробная", callback_data=f"admin:grant:plan:trial:{telegram_id}")],
            [InlineKeyboardButton(text="👉 Стандартная", callback_data=f"admin:grant:plan:standard:{telegram_id}")],
            [InlineKeyboardButton(text="👉 Расширенная", callback_data=f"admin:grant:plan:extended:{telegram_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:user:info:{telegram_id}")],
        ]
    )


def admin_promo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["admin_create_promo"], callback_data="admin:promo:create")],
            [InlineKeyboardButton(text=btn["admin_delete_promo"], callback_data="admin:promo:delete")],
            [InlineKeyboardButton(text=btn["admin_list_promo"], callback_data="admin:promo:list")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:admin")],
        ]
    )


def admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["admin_send_to_user"], callback_data="admin:broadcast:personal")],
            [InlineKeyboardButton(text=btn["admin_mass_send"], callback_data="admin:broadcast:mass")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:admin")],
        ]
    )


def confirm_delete_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin:user:confirm_delete:{telegram_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:user:info:{telegram_id}")],
        ]
    )


def admin_referral_actions_keyboard(referrer_id: int, referral_id: int) -> InlineKeyboardMarkup:
    """Actions for managing a referral relationship."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Карточка", callback_data=f"admin:user:info:{referral_id}")],
            [InlineKeyboardButton(text="🔗 Удалить привязку", callback_data=f"admin:user:unlink_referral:{referrer_id}:{referral_id}")],
            [InlineKeyboardButton(text=btn["back"], callback_data=f"admin:user:referrals:{referrer_id}")],
        ]
    )


# ─── Управление длительностями тарифов ────────────────────────────────────────

def admin_pricing_keyboard() -> InlineKeyboardMarkup:
    """Выбор тарифа для редактирования длительностей."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Стандартный", callback_data="admin:price:list:standard")],
            [InlineKeyboardButton(text="🚀 Расширенный", callback_data="admin:price:list:extended")],
            [InlineKeyboardButton(text=btn["back"], callback_data="menu:admin")],
        ]
    )


def admin_pricing_plan_keyboard(plan: str, days_options: list) -> InlineKeyboardMarkup:
    """Список существующих периодов тарифа + кнопка добавления/возврата."""
    rows: list[list[InlineKeyboardButton]] = []
    for opt in days_options:
        label = f"🗑 {opt.days} дн. — {opt.price_rub:.0f}₽ / {opt.price_usdt:.1f}$"
        rows.append([
            InlineKeyboardButton(
                text=label, callback_data=f"admin:price:del:{plan}:{opt.days}"
            )
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить период", callback_data=f"admin:price:add:{plan}")])
    rows.append([InlineKeyboardButton(text=btn["back"], callback_data="menu:admin_pricing")])
    return InlineKeyboardMarkup(inline_keyboard=rows)