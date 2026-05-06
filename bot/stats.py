from datetime import datetime, timedelta

import aiosqlite

from bot.database import get_stats


async def get_user_stats(conn: aiosqlite.Connection, user_id: int) -> str:
    """Format user statistics for display."""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    epoch = datetime(1970, 1, 1)

    today_stats = await get_stats(conn, user_id, today)
    week_stats = await get_stats(conn, user_id, week_ago)
    month_stats = await get_stats(conn, user_id, month_ago)
    total_stats = await get_stats(conn, user_id, epoch)

    def _fmt(s: dict) -> str:
        return (
            f"  Quizzes: {s['quizzes_completed']}\n"
            f"  Words added: {s['words_added']}\n"
            f"  Words learned: {s['words_learned']}"
        )

    return (
        "<b>Your Statistics</b>\n\n"
        f"<b>Today:</b>\n{_fmt(today_stats)}\n\n"
        f"<b>This week:</b>\n{_fmt(week_stats)}\n\n"
        f"<b>This month:</b>\n{_fmt(month_stats)}\n\n"
        f"<b>Overall:</b>\n{_fmt(total_stats)}"
    )
