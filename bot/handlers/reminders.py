"""Reminder commands: /remindme, /reminders, /remindoff."""

from __future__ import annotations

import html

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import MAX_REMINDERS_PER_USER
from bot.database import (
    add_reminder,
    count_reminders,
    delete_all_reminders,
    delete_reminder,
    get_reminders,
)
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning
from bot.reminders import (
    DEFAULT_TZ,
    cancel_reminder,
    format_in_zones,
    schedule_reminder,
    validate_timezone,
)
from bot.safety import LimitExceeded, ensure_db_size_allows_write, ensure_user_allowed

from ._shared import _get_conn, _safe_log

logger = get_logger(__name__)


def _parse_remindme_args(args: list[str]) -> tuple[int, int, str] | str:
    """Parse `/remindme HH:MM [tz]` args. Returns (hour, minute, tz) or an error string."""
    if not args:
        return "Usage: /remindme HH:MM [timezone]\nExample: /remindme 09:00 Europe/Berlin"
    time_str = args[0]
    if ":" not in time_str:
        return "Time must be in HH:MM format (e.g. 09:00)."
    hh, _, mm = time_str.partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        return "Time must be in HH:MM format (e.g. 09:00)."
    hour, minute = int(hh), int(mm)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return "Hour must be 0-23 and minute 0-59."
    tz = " ".join(args[1:]).strip() if len(args) > 1 else DEFAULT_TZ
    if not validate_timezone(tz):
        return f"Unknown timezone '{html.escape(tz)}'. Use IANA names like 'Europe/Berlin'."
    return hour, minute, tz


def _format_reminder_line(r: dict) -> str:
    """Render a single reminder with Berlin/Moscow times."""
    zones = format_in_zones(r["hour"], r["minute"], r["timezone"])
    src_label = html.escape(r["timezone"])
    src_time = f"{r['hour']:02d}:{r['minute']:02d}"
    return (
        f"  #{r['id']} — {src_time} {src_label} "
        f"(Berlin {zones['Europe/Berlin']}, Moscow {zones['Europe/Moscow']})"
    )


async def remindme_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/remindme {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)

    parsed = _parse_remindme_args(context.args or [])
    if isinstance(parsed, str):
        await update.message.reply_text(parsed)
        return
    hour, minute, tz = parsed

    try:
        await ensure_db_size_allows_write(conn, user_id)
        await ensure_user_allowed(conn, user_id)
        current_reminders = await count_reminders(conn, user_id)
        if current_reminders >= MAX_REMINDERS_PER_USER:
            raise LimitExceeded(
                f"You already have {current_reminders} reminder(s). The limit is "
                f"{MAX_REMINDERS_PER_USER}, so this reminder was not saved.",
                f"Max reminders per user exceeded: current={current_reminders}, "
                f"limit={MAX_REMINDERS_PER_USER}",
            )
        reminder_id = await add_reminder(conn, user_id, hour, minute, tz)
    except LimitExceeded as e:
        log_user_warning(logger, user_id, e.log_message)
        await update.message.reply_text(e.user_message)
        return
    except Exception as e:
        log_user_error(logger, user_id, f"Failed to add reminder: {e}", exc_info=e)
        await update.message.reply_text("Could not save reminder, please try again.")
        return

    reminder = {
        "id": reminder_id,
        "user_id": user_id,
        "hour": hour,
        "minute": minute,
        "timezone": tz,
    }
    schedule_reminder(context.application, reminder)

    zones = format_in_zones(hour, minute, tz)
    msg = (
        f"Reminder #{reminder_id} set for {hour:02d}:{minute:02d} {html.escape(tz)} "
        f"(Berlin {zones['Europe/Berlin']}, Moscow {zones['Europe/Moscow']})."
    )
    if tz == DEFAULT_TZ and len(context.args or []) <= 1:
        msg += f"\nDefault timezone is {DEFAULT_TZ} — pass an IANA name to override."
    await update.message.reply_text(msg)


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/reminders")
    conn = _get_conn(context)
    items = await get_reminders(conn, user_id)
    if not items:
        await update.message.reply_text("No reminders set. Use /remindme HH:MM to add one.")
        return
    lines = ["Your reminders:"] + [_format_reminder_line(r) for r in items]
    lines.append("\nRemove with /remindoff <id> or /remindoff all.")
    await update.message.reply_text("\n".join(lines))


async def remindoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/remindoff {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)

    if not context.args:
        await update.message.reply_text("Usage: /remindoff <id> or /remindoff all")
        return

    arg = context.args[0].lower()
    if arg == "all":
        items = await get_reminders(conn, user_id)
        for r in items:
            cancel_reminder(context.application, r["id"])
        count = await delete_all_reminders(conn, user_id)
        await update.message.reply_text(f"Removed {count} reminder(s).")
        return

    if not arg.isdigit():
        await update.message.reply_text("Reminder id must be a number, or 'all'.")
        return

    reminder_id = int(arg)
    cancel_reminder(context.application, reminder_id)
    deleted = await delete_reminder(conn, user_id, reminder_id)
    if deleted:
        await update.message.reply_text(f"Removed reminder #{reminder_id}.")
    else:
        await update.message.reply_text(f"No reminder #{reminder_id} found.")
