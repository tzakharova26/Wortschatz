"""Daily quiz reminders backed by python-telegram-bot's JobQueue.

Reminders are persisted in the `reminders` table and re-registered with JobQueue
on every bot startup via `load_all_reminders`. Per-reminder jobs are named
`reminder_{id}` so they can be individually cancelled.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from telegram.ext import Application, ContextTypes

from bot.database import get_all_reminders
from bot.logging_config import get_logger, log_user_error

logger = get_logger(__name__)

DEFAULT_TZ = "Europe/Berlin"
DISPLAY_ZONES = ["Europe/Berlin", "Europe/Moscow"]
REMINDER_MESSAGE = "Time to practice German! Send /quiz to start."


def job_name(reminder_id: int) -> str:
    return f"reminder_{reminder_id}"


def validate_timezone(tz: str) -> bool:
    """Return True if `tz` is a valid IANA timezone."""
    if not tz:
        return False
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def format_in_zones(hour: int, minute: int, source_tz: str) -> dict[str, str]:
    """Convert (hour, minute, source_tz) into HH:MM strings for each DISPLAY_ZONES entry.

    Uses today's date so DST handling reflects the current calendar.
    """
    src = ZoneInfo(source_tz)
    now = datetime.now(src)
    aware = datetime(now.year, now.month, now.day, hour, minute, tzinfo=src)
    return {tz: aware.astimezone(ZoneInfo(tz)).strftime("%H:%M") for tz in DISPLAY_ZONES}


async def _reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the reminder message. Catches send failures (e.g. user blocked the bot)."""
    job = context.job
    user_id = job.data["user_id"]
    try:
        await context.bot.send_message(chat_id=user_id, text=REMINDER_MESSAGE)
    except Exception as e:
        log_user_error(logger, user_id, f"Failed to send reminder: {e}", exc_info=e)


def schedule_reminder(application: Application, reminder: dict) -> None:
    """Register a daily JobQueue job for one reminder."""
    if application.job_queue is None:
        logger.warning(
            "JobQueue not available; cannot schedule reminder",
            extra={"user_id": reminder["user_id"]},
        )
        return
    tz = ZoneInfo(reminder["timezone"])
    application.job_queue.run_daily(
        callback=_reminder_callback,
        time=time(reminder["hour"], reminder["minute"], tzinfo=tz),
        name=job_name(reminder["id"]),
        data={"user_id": reminder["user_id"]},
    )


def cancel_reminder(application: Application, reminder_id: int) -> bool:
    """Remove the JobQueue job for a reminder. Returns True if a job was cancelled."""
    if application.job_queue is None:
        return False
    jobs = application.job_queue.get_jobs_by_name(job_name(reminder_id))
    if not jobs:
        return False
    for j in jobs:
        j.schedule_removal()
    return True


async def load_all_reminders(application: Application, conn: aiosqlite.Connection) -> int:
    """On startup, fetch reminders from DB and register them with JobQueue.

    Returns the number of reminders scheduled.
    """
    reminders = await get_all_reminders(conn)
    scheduled = 0
    for r in reminders:
        try:
            schedule_reminder(application, r)
            scheduled += 1
        except Exception as e:
            log_user_error(
                logger,
                r["user_id"],
                f"Failed to schedule reminder id={r['id']}: {e}",
                exc_info=e,
            )
    logger.info(
        "Scheduled %d reminder(s) on startup",
        scheduled,
        extra={"user_id": "system"},
    )
    return scheduled
