from __future__ import annotations

import logging

from aiogram import Bot

from app.database.models import PaymentStatus, PaymentSystem
from app.database.repository import Repository
from app.services.cryptobot import cryptobot
from app.services.subscription import activate_subscription, apply_referral_bonuses
from app.services.yukassa import yukassa
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

    # Mark paid
    await repo.payments.set_status(payment_id, PaymentStatus.paid)
    await repo.commit()

    # Apply referral bonuses (only on first paid subscription)
    try:
        paid_count = sum(1 for p in user.payments if p.status == PaymentStatus.paid)
    except Exception:
        paid_count = 0

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
        else:
            await bot.send_message(
                user.telegram_id,
                "Оплата прошла, но ссылку выдать не удалось (ошибка панели). Напиши в поддержку.",
            )
    except Exception as e:
        logger.warning("Failed to notify user %d: %s", user.telegram_id, e)

    logger.info(
        "Payment %s processed: user TG_%d, plan=%s, days=%d",
        payment_id,
        user.telegram_id,
        payment.plan.value,
        payment.days,
    )
    return True


async def poll_pending_payments(repo: Repository, bot: Bot) -> None:
    """Poll payment systems for pending payments. Called by scheduler."""

    # --- YuKassa ---
    yk_pending = await repo.payments.get_pending_by_system(PaymentSystem.yukassa)
    logger.info("Poll YuKassa pending=%d", len(yk_pending))

    for payment in yk_pending:
        if not payment.external_id:
            # Это почти всегда “мусорная” запись: платеж в БД создали,
            # но external_id не записали (например, create_payment упал).
            logger.warning("YuKassa pending payment %s has no external_id -> cancel", payment.id)
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()
            continue

        status = await yukassa.check_payment_status(payment.external_id)
        logger.info("YuKassa status external_id=%s -> %s", payment.external_id, status)

        if status == "succeeded":
            await process_paid_payment(repo, bot, payment.id)

        elif status == "waiting_for_capture":
            logger.warning("YuKassa payment %s waiting_for_capture", payment.external_id)

        elif status == "canceled":
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()

        elif status is None:
            logger.warning("YuKassa status is None for external_id=%s", payment.external_id)

    # --- CryptoBot ---
    cb_pending = await repo.payments.get_pending_by_system(PaymentSystem.cryptobot)
    logger.info("Poll CryptoBot pending=%d", len(cb_pending))

    for payment in cb_pending:
        if not payment.external_id:
            logger.warning("CryptoBot pending payment %s has no external_id -> cancel", payment.id)
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()
            continue

        status = await cryptobot.check_payment_status(payment.external_id)
        logger.info("CryptoBot status external_id=%s -> %s", payment.external_id, status)

        if status == "paid":
            await process_paid_payment(repo, bot, payment.id)

        elif status == "expired":
            await repo.payments.set_status(payment.id, PaymentStatus.cancelled)
            await repo.commit()