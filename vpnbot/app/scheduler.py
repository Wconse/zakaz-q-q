from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.database.engine import AsyncSessionFactory
from app.database.models import SubscriptionStatus
from app.database.repository import Repository
from app.services.payment_processor import poll_pending_payments
from app.services.remnawave import remna
from config.loader import config, messages

logger = logging.getLogger(__name__)
msg = messages.messages


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _send_safe(bot: Bot, repo: Repository, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except TelegramForbiddenError:
        await repo.users.mark_blocked(telegram_id)
        await repo.commit()
    except Exception as e:
        logger.warning("Failed to send reminder to %d: %s", telegram_id, e)


# ─── Subscription reminder logic ─────────────────────────────────────────────

BEFORE_REMINDERS = [
    # (hours_before, db_field, msg_key)
    (3 * 24, "reminded_3d", "remind_before_3d"),
    (2 * 24, "reminded_2d", "remind_before_2d"),
    (24, "reminded_1d", "remind_before_1d"),
    (12, "reminded_12h", "remind_before_12h"),
    (6, "reminded_6h", "remind_before_6h"),
    (2, "reminded_2h", "remind_before_2h"),
]

AFTER_REMINDERS = [
    # (hours_after, db_field, msg_key)
    (24, "reminded_after_1d", "remind_after_1d"),
    (48, "reminded_after_2d", "remind_after_2d"),
    (72, "reminded_after_3d", "remind_after_3d"),
    # 2h before deletion (total 5 days after expiry = 120h, warning at 118h)
    (config.scheduler.inactive_delete_days * 24 - 2, "reminded_before_delete_2h", "remind_before_delete_2h"),
]


async def check_subscriptions(bot: Bot) -> None:
    async with AsyncSessionFactory() as session:
        repo = Repository(session)
        now = _now()

        # ── Mark expired ──────────────────────────────────────────────────
        expired_subs = await repo.subscriptions.get_expired_since(now)
        for sub in expired_subs:
            sub.status = SubscriptionStatus.expired
        if expired_subs:
            await repo.commit()

        # ── Before-expiry reminders ───────────────────────────────────────
        for hours_before, field, msg_key in BEFORE_REMINDERS:
            window_start = now + timedelta(hours=hours_before - 0.5)
            window_end = now + timedelta(hours=hours_before + 0.5)
            subs = await repo.subscriptions.get_expiring_between(window_start, window_end)
            for sub in subs:
                if getattr(sub, field):
                    continue
                user = await repo.users.get_by_telegram_id(sub.user.telegram_id)
                if user and not user.blocked_bot_at:
                    from app.bot.keyboards.main import renew_keyboard
                    from aiogram.types import InlineKeyboardMarkup
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            msg[msg_key],
                            parse_mode="HTML",
                            reply_markup=renew_keyboard(),
                        )
                    except TelegramForbiddenError:
                        await repo.users.mark_blocked(user.telegram_id)
                    except Exception as e:
                        logger.warning("Reminder send failed: %s", e)
                await repo.subscriptions.mark_reminder(sub.id, field)
            await repo.commit()

        # ── After-expiry reminders ────────────────────────────────────────
        expired = await repo.subscriptions.get_by_status(SubscriptionStatus.expired)
        for sub in expired:
            if not sub.expires_at:
                continue
            hours_since = (now - sub.expires_at).total_seconds() / 3600
            user = sub.user

            for hours_after, field, msg_key in AFTER_REMINDERS:
                if hours_since >= hours_after and not getattr(sub, field):
                    if user and not user.blocked_bot_at:
                        from app.bot.keyboards.main import renew_keyboard
                        try:
                            await bot.send_message(
                                user.telegram_id,
                                msg[msg_key],
                                parse_mode="HTML",
                                reply_markup=renew_keyboard(),
                            )
                        except TelegramForbiddenError:
                            await repo.users.mark_blocked(user.telegram_id)
                        except Exception as e:
                            logger.warning("After-expiry reminder failed: %s", e)
                    await repo.subscriptions.mark_reminder(sub.id, field)

        await repo.commit()

        # ── Auto-delete inactive users ────────────────────────────────────
        delete_after_hours = config.scheduler.inactive_delete_days * 24
        for sub in expired:
            if not sub.expires_at:
                continue
            hours_since = (now - sub.expires_at).total_seconds() / 3600
            if hours_since >= delete_after_hours:
                user = sub.user
                if user and user.remnawave_uuid:
                    deleted = await remna.delete_user(user.remnawave_uuid)
                    if deleted:
                        logger.info(
                            "Auto-deleted Remnawave user for TG_%d", user.telegram_id
                        )
                        # Clear UUID but keep trial_used flag
                        await repo.users.set_remnawave_uuid(user.telegram_id, "")
                        # Actually nullify
                        from sqlalchemy import update
                        from app.database.models import User
                        await session.execute(
                            update(User)
                            .where(User.telegram_id == user.telegram_id)
                            .values(remnawave_uuid=None)
                        )
                await repo.commit()


# ─── Payment polling ──────────────────────────────────────────────────────────

async def poll_payments(bot: Bot) -> None:
    async with AsyncSessionFactory() as session:
        repo = Repository(session)
        await poll_pending_payments(repo, bot)


# ─── Database backup ──────────────────────────────────────────────────────────

async def backup_database() -> None:
    db_url = config.database.url
    backup_dir = Path(config.scheduler.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = config.scheduler.backup_keep_count

    # Only works for SQLite — for PostgreSQL use pg_dump via subprocess
    if "sqlite" in db_url:
        db_path = db_url.split("///")[-1]
        if not Path(db_path).exists():
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"bot_{ts}.db"
        shutil.copy2(db_path, dest)
        logger.info("Database backup created: %s", dest)

        # Prune old backups
        backups = sorted(backup_dir.glob("bot_*.db"))
        for old in backups[:-keep]:
            old.unlink()
            logger.info("Pruned old backup: %s", old)
    else:
        # PostgreSQL backup via pg_dump
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"bot_{ts}.sql"
        proc = await asyncio.create_subprocess_shell(
            f'pg_dump "{db_url.replace("postgresql+asyncpg", "postgresql")}" > {dest}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            logger.info("PostgreSQL backup created: %s", dest)
            backups = sorted(backup_dir.glob("bot_*.sql"))
            for old in backups[:-keep]:
                old.unlink()
        else:
            logger.error("pg_dump failed for backup")


# ─── Remnawave backup ─────────────────────────────────────────────────────────

async def backup_remnawave() -> None:
    """Скачать пользователей панели Remnawave и сохранить в JSON.

    Если API не подключен (или вернул ошибку) — пишем error-stub с timestamp,
    чтобы видеть в логах/файлах попытки бэкапа. Ротация — общая по
    `backup_keep_count`.
    """
    backup_dir = Path(config.scheduler.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = config.scheduler.backup_keep_count
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    users = await remna.list_all_users()
    if users is None:
        # API не подключен или вернул ошибку — пишем заглушку с маркером
        dest = backup_dir / f"remnawave_{ts}.error.txt"
        dest.write_text(
            f"Remnawave backup attempt at {ts} failed: API unavailable or returned error.\n"
            f"base_url={config.remnawave.base_url}\n",
            encoding="utf-8",
        )
        logger.warning("Remnawave backup: API unavailable, stub written to %s", dest)
    else:
        dest = backup_dir / f"remnawave_{ts}.json"
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(
                {"backup_at": ts, "user_count": len(users), "users": users},
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        logger.info("Remnawave backup created: %s (%d users)", dest, len(users))

    # Ротация — храним последние N комбинированных файлов (json + error)
    files = sorted(
        list(backup_dir.glob("remnawave_*.json"))
        + list(backup_dir.glob("remnawave_*.error.txt"))
    )
    for old in files[:-keep]:
        try:
            old.unlink()
            logger.info("Pruned old Remnawave backup: %s", old)
        except OSError as e:
            logger.warning("Failed to prune backup %s: %s", old, e)


# ─── Scheduler runner ─────────────────────────────────────────────────────────

async def run_scheduler(bot: Bot) -> None:
    """Main scheduler loop. Run as a background asyncio task."""
    logger.info("Scheduler started")
    backup_interval = config.scheduler.backup_interval_hours * 3600
    last_backup = 0.0

    while True:
        try:
            await check_subscriptions(bot)
        except Exception as e:
            logger.error("Scheduler check_subscriptions error: %s", e)

        try:
            await poll_payments(bot)
        except Exception as e:
            logger.error("Scheduler poll_payments error: %s", e)

        try:
            now_ts = datetime.now().timestamp()
            if now_ts - last_backup >= backup_interval:
                await backup_database()
                await backup_remnawave()
                last_backup = now_ts
        except Exception as e:
            logger.error("Scheduler backup error: %s", e)

        await asyncio.sleep(60)  # Run every minute
