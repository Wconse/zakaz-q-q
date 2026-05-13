from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    BroadcastLog,
    Payment,
    PaymentStatus,
    PaymentSystem,
    PlanType,
    PromoCode,
    PromoUse,
    Subscription,
    SubscriptionStatus,
    User,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Users ────────────────────────────────────────────────────────────────────
class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, user_id: int) -> User | None:
        """Get user by primary key (users.id)."""
        return await self._s.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        r = await self._s.execute(select(User).where(User.telegram_id == telegram_id))
        return r.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        clean = username.lstrip("@")
        r = await self._s.execute(select(User).where(User.username == clean))
        return r.scalar_one_or_none()

    async def get_all(self) -> list[User]:
        r = await self._s.execute(select(User))
        return list(r.scalars().all())

    async def get_new_since(self, hours: int = 24) -> list[User]:
        since = _now() - timedelta(hours=hours)
        r = await self._s.execute(select(User).where(User.created_at >= since))
        return list(r.scalars().all())

    async def get_blocked(self) -> list[User]:
        r = await self._s.execute(select(User).where(User.blocked_bot_at.is_not(None)))
        return list(r.scalars().all())

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        referred_by: int | None = None,
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)

        if user:
            # Update username/name if changed
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referred_by=referred_by,
        )
        self._s.add(user)
        await self._s.flush()
        return user, True

    async def mark_trial_used(self, telegram_id: int) -> None:
        await self._s.execute(
            update(User).where(User.telegram_id == telegram_id).values(trial_used=True)
        )

    async def mark_trial_unused(self, telegram_id: int) -> None:
        """Reset trial_used flag so user can use trial again."""
        await self._s.execute(
            update(User).where(User.telegram_id == telegram_id).values(trial_used=False)
        )

    async def mark_blocked(self, telegram_id: int) -> None:
        await self._s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(blocked_bot_at=_now())
        )

    async def mark_unblocked(self, telegram_id: int) -> None:
        await self._s.execute(
            update(User).where(User.telegram_id == telegram_id).values(blocked_bot_at=None)
        )

    async def set_remnawave_uuid(self, telegram_id: int, uuid: str | None) -> None:
        await self._s.execute(
            update(User).where(User.telegram_id == telegram_id).values(remnawave_uuid=uuid)
        )

    async def count_referrals(self, telegram_id: int) -> int:
        r = await self._s.execute(select(func.count()).where(User.referred_by == telegram_id))
        return r.scalar_one()

    async def get_referrals(self, telegram_id: int) -> list[User]:
        """Get list of users referred by this user."""
        r = await self._s.execute(select(User).where(User.referred_by == telegram_id))
        return list(r.scalars().all())

    async def add_referral_bonus(self, telegram_id: int, days: int) -> None:
        await self._s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(referral_bonus_days=User.referral_bonus_days + days)
        )

    async def clear_referrer(self, telegram_id: int) -> None:
        """Clear the referrer for a user."""
        await self._s.execute(
            update(User).where(User.telegram_id == telegram_id).values(referred_by=None)
        )

    async def delete(self, telegram_id: int) -> None:
        """Delete user."""
        await self._s.execute(delete(User).where(User.telegram_id == telegram_id))


# ─── Subscriptions ────────────────────────────────────────────────────────────
class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active_by_user_id(self, user_id: int) -> Subscription | None:
        r = await self._s.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
            )
            .order_by(Subscription.created_at.desc())
        )
        return r.scalar_one_or_none()

    async def get_last_by_user_id_and_plan(self, user_id: int, plan: PlanType) -> Subscription | None:
        """
        Последняя подписка по конкретному плану (например trial) независимо от статуса.
        Нужна, чтобы доставать старую subscription_url и не создавать/не перезаписывать подписку.
        """
        r = await self._s.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.plan == plan,
            )
            .order_by(Subscription.created_at.desc())
        )
        return r.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        plan: PlanType,
        days: int,
        devices_limit: int,
        subscription_url: str | None = None,
    ) -> Subscription:
        # Expire previous active subs
        await self._s.execute(
            update(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
            )
            .values(status=SubscriptionStatus.expired)
        )

        expires = _now() + timedelta(days=days)
        sub = Subscription(
            user_id=user_id,
            plan=plan,
            devices_limit=devices_limit,
            expires_at=expires,
            subscription_url=subscription_url,
        )

        self._s.add(sub)
        await self._s.flush()
        return sub

    async def extend(self, sub_id: int, days: int) -> None:
        sub = await self._s.get(Subscription, sub_id)

        if sub and sub.expires_at:
            sub.expires_at = sub.expires_at + timedelta(days=days)
        elif sub:
            sub.expires_at = _now() + timedelta(days=days)

    async def set_url(self, sub_id: int, url: str) -> None:
        await self._s.execute(
            update(Subscription).where(Subscription.id == sub_id).values(subscription_url=url)
        )

    async def set_devices_limit(self, sub_id: int, devices: int) -> None:
        await self._s.execute(
            update(Subscription).where(Subscription.id == sub_id).values(devices_limit=devices)
        )

    async def expire(self, sub_id: int) -> None:
        await self._s.execute(
            update(Subscription)
            .where(Subscription.id == sub_id)
            .values(status=SubscriptionStatus.expired)
        )

    async def get_expiring_between(self, dt_from: datetime, dt_to: datetime) -> list[Subscription]:
        r = await self._s.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at.between(dt_from, dt_to),
            )
        )
        return list(r.scalars().all())

    async def get_expired_since(self, dt: datetime) -> list[Subscription]:
        """Active-status subs that have passed expiry — we need to mark them."""
        r = await self._s.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at <= dt,
            )
        )
        return list(r.scalars().all())

    async def get_by_status(self, status: SubscriptionStatus) -> list[Subscription]:
        r = await self._s.execute(select(Subscription).where(Subscription.status == status))
        return list(r.scalars().all())

    async def mark_reminder(self, sub_id: int, field: str) -> None:
        await self._s.execute(
            update(Subscription).where(Subscription.id == sub_id).values(**{field: True})
        )


# ─── Payments ─────────────────────────────────────────────────────────────────
class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        user_id: int,
        plan: PlanType,
        days: int,
        amount: float,
        currency: str,
        payment_system: PaymentSystem,
    ) -> Payment:
        p = Payment(
            user_id=user_id,
            plan=plan,
            days=days,
            amount=amount,
            currency=currency,
            payment_system=payment_system,
        )
        self._s.add(p)
        await self._s.flush()
        return p

    async def get(self, payment_id: str) -> Payment | None:
        return await self._s.get(Payment, payment_id)

    async def get_by_external_id(self, external_id: str) -> Payment | None:
        r = await self._s.execute(select(Payment).where(Payment.external_id == external_id))
        return r.scalar_one_or_none()

    async def set_status(
        self,
        payment_id: str,
        status: PaymentStatus,
        external_id: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if external_id:
            values["external_id"] = external_id
        if status == PaymentStatus.paid:
            values["paid_at"] = _now()

        await self._s.execute(update(Payment).where(Payment.id == payment_id).values(**values))

    async def get_pending_by_system(self, system: PaymentSystem) -> list[Payment]:
        r = await self._s.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.pending,
                Payment.payment_system == system,
            )
        )
        return list(r.scalars().all())


# ─── Promos ───────────────────────────────────────────────────────────────────
class PromoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, code: str, days: int, created_by: int | None = None) -> PromoCode:
        p = PromoCode(code=code.upper(), days=days, created_by=created_by)
        self._s.add(p)
        await self._s.flush()
        return p

    async def get_by_code(self, code: str) -> PromoCode | None:
        r = await self._s.execute(select(PromoCode).where(PromoCode.code == code.upper()))
        return r.scalar_one_or_none()

    async def get_all(self) -> list[PromoCode]:
        r = await self._s.execute(select(PromoCode))
        return list(r.scalars().all())

    async def delete_by_code(self, code: str) -> bool:
        promo = await self.get_by_code(code)
        if not promo:
            return False
        await self._s.delete(promo)
        return True

    async def has_used(self, promo_id: int, user_id: int) -> bool:
        r = await self._s.execute(
            select(PromoUse).where(PromoUse.promo_id == promo_id, PromoUse.user_id == user_id)
        )
        return r.scalar_one_or_none() is not None

    async def get_used_promos_by_user(self, user_id: int) -> list[tuple[PromoCode, PromoUse]]:
        """Get all promos used by a specific user with their usage info."""
        r = await self._s.execute(
            select(PromoCode, PromoUse).join(PromoUse).where(PromoUse.user_id == user_id)
        )
        return list(r.all())

    async def record_use(self, promo_id: int, user_id: int) -> None:
        u = PromoUse(promo_id=promo_id, user_id=user_id)
        self._s.add(u)
        await self._s.flush()

    async def delete_use(self, promo_id: int, user_id: int) -> bool:
        """Remove a single usage record."""
        use = await self._s.execute(
            select(PromoUse).where(PromoUse.promo_id == promo_id, PromoUse.user_id == user_id)
        )
        promo_use = use.scalar_one_or_none()
        if promo_use:
            await self._s.delete(promo_use)
            return True
        return False


# ─── Repository ───────────────────────────────────────────────────────────────
class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.payments = PaymentRepository(session)
        self.promos = PromoRepository(session)

    async def commit(self) -> None:
        await self.session.commit()