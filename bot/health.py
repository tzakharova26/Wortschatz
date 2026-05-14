from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite

from bot import logging_config
from bot.config import (
    DB_SIZE_HARD_LIMIT_MB,
    DB_SIZE_WARNING_MB,
    MAX_REMINDERS_PER_USER,
    MAX_USERS,
    MAX_WORDS_PER_USER,
)
from bot.database import DB_PATH, get_learning_overview
from bot.i18n import normalize_language
from bot.reminders import DEFAULT_TZ

_HEALTH_TZ = ZoneInfo(DEFAULT_TZ)


@dataclass(frozen=True)
class HealthSnapshot:
    known_users: int
    total_words: int
    max_words_for_user: int
    total_reminders: int
    db_size_mb: float
    due_review: int
    needs_learning: int
    review_words: int
    warnings_today: int
    errors_today: int
    last_quiz_at: str | None
    last_learn_at: str | None

    @property
    def status(self) -> str:
        if self.db_size_mb >= DB_SIZE_HARD_LIMIT_MB or self.errors_today > 0:
            return "critical"
        if (
            self.db_size_mb >= DB_SIZE_WARNING_MB
            or self.known_users >= MAX_USERS
            or self.max_words_for_user >= MAX_WORDS_PER_USER
            or self.warnings_today > 0
        ):
            return "warning"
        return "ok"


async def collect_health_snapshot(
    conn: aiosqlite.Connection,
    owner_user_id: int,
    db_path: str = DB_PATH,
    log_path: str = logging_config.LOG_FILE,
) -> HealthSnapshot:
    overview = await get_learning_overview(conn, owner_user_id)
    warnings_today, errors_today = _count_log_levels_today(log_path)
    return HealthSnapshot(
        known_users=await _count_known_users(conn),
        total_words=await _count_total(conn, "words"),
        max_words_for_user=await _max_words_for_user(conn),
        total_reminders=await _count_total(conn, "reminders"),
        db_size_mb=_db_size_mb(db_path),
        due_review=overview["due_review"],
        needs_learning=overview["needs_learning"],
        review_words=overview["review_words"],
        warnings_today=warnings_today,
        errors_today=errors_today,
        last_quiz_at=await _last_activity(conn, "quiz"),
        last_learn_at=await _last_activity(conn, "learn"),
    )


def format_health_snapshot(snapshot: HealthSnapshot, lang: str = "en") -> str:
    lang = normalize_language(lang)
    status_label = _status_label(snapshot.status, lang)
    last_quiz = _format_timestamp(snapshot.last_quiz_at, lang)
    last_learn = _format_timestamp(snapshot.last_learn_at, lang)

    if lang == "ru":
        return (
            "<b>Состояние бота</b>\n\n"
            f"Статус: <b>{status_label}</b>\n"
            f"Пользователи: {snapshot.known_users}/{MAX_USERS}\n"
            f"Слова: {snapshot.total_words} всего, максимум у пользователя "
            f"{snapshot.max_words_for_user}/{MAX_WORDS_PER_USER}\n"
            f"Очередь /learn: {snapshot.needs_learning}\n"
            f"Пора повторить: {snapshot.due_review}\n"
            f"В повторении: {snapshot.review_words}\n"
            f"Напоминания: {snapshot.total_reminders} "
            f"(лимит {MAX_REMINDERS_PER_USER} на пользователя)\n"
            f"База данных: {snapshot.db_size_mb:.1f} MB "
            f"(warning {DB_SIZE_WARNING_MB}, hard {DB_SIZE_HARD_LIMIT_MB})\n"
            f"Логи сегодня: WARNING {snapshot.warnings_today}, ERROR {snapshot.errors_today}\n"
            f"Последний quiz: {last_quiz}\n"
            f"Последний learn: {last_learn}"
        )
    return (
        "<b>Bot health</b>\n\n"
        f"Status: <b>{status_label}</b>\n"
        f"Users: {snapshot.known_users}/{MAX_USERS}\n"
        f"Words: {snapshot.total_words} total, max for one user "
        f"{snapshot.max_words_for_user}/{MAX_WORDS_PER_USER}\n"
        f"Learning queue: {snapshot.needs_learning}\n"
        f"Due review: {snapshot.due_review}\n"
        f"Review rotation: {snapshot.review_words}\n"
        f"Reminders: {snapshot.total_reminders} "
        f"({MAX_REMINDERS_PER_USER} max per user)\n"
        f"Database: {snapshot.db_size_mb:.1f} MB "
        f"(warning {DB_SIZE_WARNING_MB}, hard {DB_SIZE_HARD_LIMIT_MB})\n"
        f"Logs today: WARNING {snapshot.warnings_today}, ERROR {snapshot.errors_today}\n"
        f"Last quiz: {last_quiz}\n"
        f"Last learn: {last_learn}"
    )


async def _count_known_users(conn: aiosqlite.Connection) -> int:
    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM (
            SELECT user_id FROM words
            UNION
            SELECT user_id FROM sm2_state
            UNION
            SELECT user_id FROM quiz_history
            UNION
            SELECT user_id FROM reminders
            UNION
            SELECT user_id FROM user_settings
        ) users
        """
    )
    row = await cursor.fetchone()
    return row["cnt"] or 0


async def _count_total(conn: aiosqlite.Connection, table: str) -> int:
    if table not in {"words", "reminders"}:
        raise ValueError(f"Unsupported table: {table}")
    cursor = await conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}")  # noqa: S608
    row = await cursor.fetchone()
    return row["cnt"] or 0


async def _max_words_for_user(conn: aiosqlite.Connection) -> int:
    cursor = await conn.execute(
        """
        SELECT COALESCE(MAX(cnt), 0) AS cnt
        FROM (
            SELECT COUNT(*) AS cnt
            FROM words
            GROUP BY user_id
        )
        """
    )
    row = await cursor.fetchone()
    return row["cnt"] or 0


async def _last_activity(conn: aiosqlite.Connection, source: str) -> str | None:
    cursor = await conn.execute(
        "SELECT MAX(answered_at) AS last_at FROM quiz_history WHERE source = ?",
        (source,),
    )
    row = await cursor.fetchone()
    return row["last_at"]


def _db_size_mb(db_path: str) -> float:
    try:
        return os.path.getsize(db_path) / (1024 * 1024)
    except OSError:
        return 0.0


def _count_log_levels_today(log_path: str) -> tuple[int, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    warnings = 0
    errors = 0
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                if not line.startswith(f"[{today}"):
                    continue
                if "] WARNING " in line:
                    warnings += 1
                elif "] ERROR " in line:
                    errors += 1
    except OSError:
        return 0, 0
    return warnings, errors


def _status_label(status: str, lang: str) -> str:
    if lang == "ru":
        return {"ok": "OK", "warning": "Внимание", "critical": "Критично"}[status]
    return {"ok": "OK", "warning": "Warning", "critical": "Critical"}[status]


def _format_timestamp(value: str | None, lang: str) -> str:
    if not value:
        return "никогда" if lang == "ru" else "never"
    parsed = _parse_db_timestamp(value)
    if parsed is None:
        return value
    local = parsed.astimezone(_HEALTH_TZ)
    now = datetime.now(_HEALTH_TZ)
    if local.date() == now.date():
        prefix = "сегодня" if lang == "ru" else "today"
        return f"{prefix} {local:%H:%M}"
    if local.date() == (now - timedelta(days=1)).date():
        prefix = "вчера" if lang == "ru" else "yesterday"
        return f"{prefix} {local:%H:%M}"
    return local.strftime("%Y-%m-%d %H:%M")


def _parse_db_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
