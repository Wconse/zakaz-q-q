from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.database.models import PlanType
from app.database.repository import Repository
from app.services.remnawave import remna
from config.loader import prices

logger = logging.getLogger(__name__)


async def activate_subscription(
    repo: Repository,
    telegram_id: int,
    username: str | None,
    plan: PlanType,
    days: int,
) -> str | None:
    """
    Create or update user in Remnawave, create subscription record in DB.
    Returns subscription URL on success, None on failure.
    """
    from app.database.models import PlanType as PT

    plan_key = plan.value
    # Use hwid_device_limit — the correct Remnawave API field name
    devices_limit = _devices_for_plan(plan_key)

    # Calculate expiry
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    expire_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get or create user record
    user = await repo.users.get_by_telegram_id(telegram_id)
    if not user:
        user, _ = await repo.users.get_or_create(telegram_id, username)
        await repo.commit()

    sub_url: str | None = None

    if user.remnawave_uuid:
        # User already exists in panel — update
        remna_user = await remna.update_user(
            uuid=user.remnawave_uuid,
            expire_at=expire_iso,
            hwid_device_limit=devices_limit,
        )
        if remna_user:
            sub_url = remna_user.subscription_url
            logger.info("Remnawave user updated: %s", user.remnawave_uuid)
        else:
            logger.error("Failed to update Remnawave user %s", user.remnawave_uuid)
    else:
        # Create new user in panel
        remna_user = await remna.create_user(
            telegram_id=telegram_id,
            username=username,
            plan=plan_key,
            expire_at=expire_iso,
            hwid_device_limit=devices_limit,
        )
        if remna_user:
            sub_url = remna_user.subscription_url
            await repo.users.set_remnawave_uuid(telegram_id, remna_user.uuid)
            await repo.commit()
            logger.info("Remnawave user created: TG_%d → %s", telegram_id, remna_user.uuid)
        else:
            logger.error("Failed to create Remnawave user for TG_%d", telegram_id)

    # Create subscription record in DB
    sub = await repo.subscriptions.create(
        user_id=user.id,
        plan=plan,
        days=days,
        devices_limit=devices_limit,
        subscription_url=sub_url,
    )
    await repo.commit()

    return sub_url


async def apply_referral_bonuses(
    repo: Repository,
    new_user_telegram_id: int,
    inviter_telegram_id: int | None,
) -> None:
    """Apply referral bonuses to both parties after first payment."""
    from config.loader import prices as p

    if not inviter_telegram_id:
        return

    inviter = await repo.users.get_by_telegram_id(inviter_telegram_id)
    if not inviter:
        return

    invitee_bonus = p.referral.invitee_bonus_days
    inviter_bonus = p.referral.inviter_bonus_days

    # Bonus for new user
    invitee = await repo.users.get_by_telegram_id(new_user_telegram_id)
    if invitee:
        sub = await repo.subscriptions.get_active_by_user_id(invitee.id)
        if sub:
            await repo.subscriptions.extend(sub.id, invitee_bonus)
            # Also update Remnawave
            if invitee.remnawave_uuid and sub.expires_at:
                new_exp = (sub.expires_at + __import__("datetime").timedelta(days=invitee_bonus))
                await remna.update_user(
                    uuid=invitee.remnawave_uuid,
                    expire_at=new_exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )

    # Bonus for inviter
    inviter_sub = await repo.subscriptions.get_active_by_user_id(inviter.id)
    await repo.users.add_referral_bonus(inviter_telegram_id, inviter_bonus)
    if inviter_sub:
        await repo.subscriptions.extend(inviter_sub.id, inviter_bonus)
        if inviter.remnawave_uuid and inviter_sub.expires_at:
            new_exp = (inviter_sub.expires_at + __import__("datetime").timedelta(days=inviter_bonus))
            await remna.update_user(
                uuid=inviter.remnawave_uuid,
                expire_at=new_exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
    await repo.commit()


def _devices_for_plan(plan_key: str) -> int:
    if plan_key == "standard":
        return prices.standard.devices
    elif plan_key == "extended":
        return prices.extended.devices
    return prices.trial.devices
