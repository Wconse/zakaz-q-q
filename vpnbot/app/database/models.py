from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PlanType(str, enum.Enum):
    trial = "trial"
    standard = "standard"
    extended = "extended"


class PaymentSystem(str, enum.Enum):
    yukassa = "yukassa"
    cryptobot = "cryptobot"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


# ─── User ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))

    # Remnawave
    remnawave_uuid: Mapped[str | None] = mapped_column(String(64), unique=True)

    # Referral
    referred_by: Mapped[int | None] = mapped_column(BigInteger)
    referral_bonus_days: Mapped[int] = mapped_column(Integer, default=0)

    # Trial tracking — persists even if user is deleted from panel
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bot status
    blocked_bot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="user", lazy="selectin")
    payments: Mapped[list[Payment]] = relationship(back_populates="user", lazy="selectin")


# ─── Subscription ─────────────────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.active
    )

    devices_limit: Mapped[int] = mapped_column(Integer, default=3)
    subscription_url: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Reminder tracking (which reminders were sent)
    reminded_3d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_2d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_1d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_12h: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_6h: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_2h: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_after_1d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_after_2d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_after_3d: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_before_delete_2h: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="subscriptions")


# ─── Payment ──────────────────────────────────────────────────────────────────

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_system: Mapped[PaymentSystem] = mapped_column(Enum(PaymentSystem), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.pending
    )
    external_id: Mapped[str | None] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="payments")


# ─── Promo code ──────────────────────────────────────────────────────────────

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    uses: Mapped[list[PromoUse]] = relationship(back_populates="promo", lazy="selectin")


class PromoUse(Base):
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    promo: Mapped[PromoCode] = relationship(back_populates="uses")


# ─── Broadcast log ────────────────────────────────────────────────────────────

class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_text: Mapped[str] = mapped_column(Text)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
