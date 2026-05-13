from __future__ import annotations

import asyncio
import json
import logging
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


def _as_aware_utc(dt: datetime) -> datetime:
    """
    SQLite часто отдаёт datetime без tzinfo (naive).
    Для арифметики делаем aware UTC, чтобы не падать.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# (hours_before, db_field, msg_key)
BEFORE_REMINDERS = [
    (3 * 24, "reminded_3d", "remind_before_3d"),
    (2 * 24, "reminded_2d", "remind_before_2d"),
    (24, "reminded_1d", "remind_before_1d"),
    (12, "reminded_12h", "remind_before_12h"),
    (6, "reminded_6h", "remind_before_6h"),
    (2, "reminded_2h", "remind_before_2h"),
]

# (hours_after, db_field, msg_key)
AFTER_REMINDERS = [
    (24, "reminded_after_1d", "remind_after_1d"),
    (48, "reminded_after_2d", "remind_after_2d"),
    (72, "reminded_after_3d", "remind_after_3d"),
    (
        config.scheduler.inactive_delete_days * 24 - 2,
        "reminded_before_delete_2h",
        "remind_before_delete_2h",
    ),
]


async def _send_reminder(bot: Bot, repo: Repository, telegram_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramForbiddenError:
        await repo.users.mark_blocked(telegram_id)
        await repo.commit()
    except Exception as e:
        logger.warning("Failed to send message to %d: %s", telegram_id, e)


async def check_subscriptions(bot: Bot) -> None:
    """
    ВАЖНО: здесь НЕЛЬЗЯ трогать sub.user (relationship) — это вызывает greenlet_spawn.
    Всегда берём пользователя отдельным запросом: repo.users.get(sub.user_id).
    """
    async with AsyncSessionFactory() as session:
        repo = Repository(session)
        now = _now()

        # 1) Пометить просроченные active -> expired
        expired_subs = await repo.subscriptions.get_expired_since(now)
        for sub in expired_subs:
            sub.status = SubscriptionStatus.expired
        if expired_subs:
            await repo.commit()

        # 2) Напоминания ДО окончания
        for hours_before, field, msg_key in BEFORE_REMINDERS:
            window_start = now + timedelta(hours=hours_before - 0.5)
            window_end = now + timedelta(hours=hours_before + 0.5)

            subs = await repo.subscriptions.get_expiring_between(window_start, window_end)
            for sub in subs:
                if getattr(sub, field):
                    continue

                user = await repo.users.get(sub.user_id)
                if user and not user.blocked_bot_at:
                    from app.bot.keyboards.main import renew_keyboard
                    await _send_reminder(
                        bot,
                        repo,
                        user.telegram_id,
                        msg[msg_key],
                        reply_markup=renew_keyboard(),
                    )

                await repo.subscriptions.mark_reminder(sub.id, field)
                await repo.commit()

        # 3) Напоминания ПОСЛЕ окончания + автоделит
        expired = await repo.subscriptions.get_by_status(SubscriptionStatus.expired)

        delete_after_hours = config.scheduler.inactive_delete_days * 24

        for sub in expired:
            if not sub.expires_at:
                continue

            expires_at = _as_aware_utc(sub.expires_at)
            hours_since = (now - expires_at).total_seconds() / 3600

            user = await repo.users.get(sub.user_id)

            # after-expiry reminders
            for hours_after, field, msg_key in AFTER_REMINDERS:
                if hours_since >= hours_after and not getattr(sub, field):
                    if user and not user.blocked_bot_at:
                        from app.bot.keyboards.main import renew_keyboard
                        await _send_reminder(
                            bot,
                            repo,
                            user.telegram_id,
                            msg[msg_key],
                            reply_markup=renew_keyboard(),
                        )

                    await repo.subscriptions.mark_reminder(sub.id, field)
                    await repo.commit()

            # auto-delete from Remnawave after N days (only if no active subscription)
            if hours_since >= delete_after_hours and user and user.remnawave_uuid:
                # Check if user has any active subscription
                active_sub = await repo.subscriptions.get_active_by_user_id(user.id)
                if active_sub:
                    continue  # User has active subscription, don't delete from panel

                deleted = await remna.delete_user(user.remnawave_uuid)
                if deleted:
                    logger.info("Auto-deleted Remnawave user for TG_%d", user.telegram_id)

                # очистим remnawave_uuid в БД (trial_used не трогаем)
                await repo.users.set_remnawave_uuid(user.telegram_id, None)
                await repo.commit()


async def poll_payments(bot: Bot) -> None:
    async with AsyncSessionFactory() as session:
        repo = Repository(session)
        await poll_pending_payments(repo, bot)


async def backup_database() -> None:
    db_url = config.database.url
    backup_dir = Path(config.scheduler.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = config.scheduler.backup_keep_count

    if "sqlite" in db_url:
        db_path = db_url.split("///")[-1]
        src = Path(db_path)
        if not src.exists():
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"bot_{ts}.db"
        shutil.copy2(src, dest)
        logger.info("Database backup created: %s", dest)

        backups = sorted(backup_dir.glob("bot_*.db"))
        for old in backups[:-keep]:
            old.unlink()
            logger.info("Pruned old backup: %s", old)

    else:
        # как было у тебя: pg_dump через shell (оставляем)
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


async def backup_remnawave() -> None:
    backup_dir = Path(config.scheduler.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    keep = config.scheduler.backup_keep_count
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    users = await remna.list_all_users()

    if users is None:
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

    files = sorted(
        list(backup_dir.glob("remnawave_*.json")) + list(backup_dir.glob("remnawave_*.error.txt"))
    )
    for old in files[:-keep]:
        try:
            old.unlink()
            logger.info("Pruned old Remnawave backup: %s", old)
        except OSError as e:
            logger.warning("Failed to prune backup %s: %s", old, e)


async def run_scheduler(bot: Bot) -> None:
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

        await asyncio.sleep(60)