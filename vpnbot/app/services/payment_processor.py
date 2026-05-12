from __future__ import annotations

import logging
from datetime import timezone

from aiogram import Bot

from app.database.models import PaymentStatus, PaymentSystem
from app.database.repository import Repository
from app.services.cryptobot import cryptobot
from app.services.yukassa import yukassa
from app.services.subscription import activate_subscription, apply_referral_bonuses
from config.loader import messages

logger = logging.getLogger(__name__)
msg = messages.messages


async def process_paid_payment(
    repo: Repository,
    bot: Bot,
    payment_id: str,
) -> bool:
    """
    Called when we confirm a payment is paid.
    Activates subscription and notifies user.
    Returns True if processed successfully.
    """
    payment = await repo.payments.get(payment_id)
    if not payment:
        logger.warning("process_paid_payment: payment %s not found", payment_id)
        return False

    if payment.status == PaymentStatus.paid:
        return True  # Already processed

    # Mark paid
    await repo.payments.set_status(payment_id, PaymentStatus.paid)
    await repo.commit()

    # Get user
    user = await repo.users.get(payment.user_id)
    if not user:
        logger.error("process_paid_payment: user_id %d not found", payment.user_id)
        return False

    # Activate subscription in Remnawave + DB
    sub_url = await activate_subscription(
        repo=repo,
        telegram_id=user.telegram_id,
        username=user.username,
        plan=payment.plan,
        days=payment.days,
    )

    # Apply referral bonuses (only on first paid subscription)
    paid_count = sum(
        1 for p in user.payments if p.status == PaymentStatus.paid
    )
    if paid_count == 1 and user.referred_by:
        await apply_referral_bonuses(
            repo=repo,
            new_user_telegram_id=user.telegram_id,
            inviter_telegram_id=user.referred_by,
        )

    # Notify user
    try:
        plan_name = messages.plans.get(payment.plan.value, payment.plan.value)
        text = (
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"Тариф: <b>{plan_name}</b>\n"
            f"Срок: <b>{payment.days} дней</b>\n\n"
        )
        await bot.send_message(user.telegram_id, text, parse_mode="HTML")

        if sub_url:
            link_text = msg["subscription_link"].format(link=sub_url)
            await bot.send_message(user.telegram_id, link_text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Failed to notify user %d: %s", user.telegram_id, e)

    logger.info(
        "Payment %s processed: user TG_%d, plan=%s, days=%d",
        payment_id, user.telegram_id, payment.plan.value, payment.days,
    )
    return True


async def poll_pending_payments(repo: Repository, bot: Bot) -> None:
    """Poll payment systems for pending payments. Called by scheduler."""
    # YuKassa
    yk_pending = await repo.payments.get_pending_by_system(PaymentSystem.yukassa)
    for payment in yk_pending:
        if not payment.external_id:
            continue
        status = await yukassa.check_payment_status(payment.external_id)
        if status == "succeeded":
            await process_paid_payment(repo, bot, payment.id)
        elif status == "canceled":
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()

    # CryptoBot
    cb_pending = await repo.payments.get_pending_by_system(PaymentSystem.cryptobot)
    for payment in cb_pending:
        if not payment.external_id:
            continue
        status = await cryptobot.check_payment_status(payment.external_id)
        if status == "paid":
            await process_paid_payment(repo, bot, payment.id)
        elif status == "expired":
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()
