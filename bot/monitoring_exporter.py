from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from prometheus_client import Gauge, start_http_server

from bot.config import DB_SIZE_HARD_LIMIT_MB, DB_SIZE_WARNING_MB, MAX_USERS, MAX_WORDS_PER_USER
from bot.database import DB_PATH
from bot.logging_config import LOG_FILE

EXPORTER_PORT = int(os.getenv("MONITORING_EXPORTER_PORT", "9108"))
SCRAPE_INTERVAL_SECONDS = int(os.getenv("MONITORING_EXPORTER_INTERVAL", "15"))

known_users = Gauge("wortschatz_known_users", "Known Telegram users with persisted bot data")
words_total = Gauge("wortschatz_words_total", "Total saved word cards")
words_max_per_user = Gauge(
    "wortschatz_words_max_per_user", "Largest saved word-card count for one user"
)
reminders_total = Gauge("wortschatz_reminders_total", "Total configured reminders")
quiz_answers_total = Gauge(
    "wortschatz_quiz_answers_total", "Total quiz_history rows by source", ["source"]
)
due_review_words = Gauge("wortschatz_due_review_words", "Words currently due for SM-2 review")
learning_queue_words = Gauge(
    "wortschatz_learning_queue_words", "Words currently waiting for /learn"
)
db_size_bytes = Gauge("wortschatz_db_size_bytes", "SQLite database size in bytes")
db_size_warning_bytes = Gauge("wortschatz_db_size_warning_bytes", "Configured DB warning threshold")
db_size_hard_limit_bytes = Gauge("wortschatz_db_size_hard_limit_bytes", "Configured DB hard limit")
max_users_limit = Gauge("wortschatz_max_users_limit", "Configured max user count")
max_words_per_user_limit = Gauge(
    "wortschatz_max_words_per_user_limit", "Configured max word count per user"
)
log_warnings_today = Gauge("wortschatz_log_warnings_today", "Warning log lines for the current day")
log_errors_today = Gauge("wortschatz_log_errors_today", "Error log lines for the current day")


def main() -> None:
    db_size_warning_bytes.set(DB_SIZE_WARNING_MB * 1024 * 1024)
    db_size_hard_limit_bytes.set(DB_SIZE_HARD_LIMIT_MB * 1024 * 1024)
    max_users_limit.set(MAX_USERS)
    max_words_per_user_limit.set(MAX_WORDS_PER_USER)
    start_http_server(EXPORTER_PORT)
    while True:
        update_metrics()
        time.sleep(SCRAPE_INTERVAL_SECONDS)


def update_metrics(db_path: str = DB_PATH, log_path: str = LOG_FILE) -> None:
    db_size_bytes.set(_file_size(db_path))
    warnings, errors = _count_log_levels_today(log_path)
    log_warnings_today.set(warnings)
    log_errors_today.set(errors)

    if not Path(db_path).exists():
        _set_empty_db_metrics()
        return

    try:
        uri = f"file:{db_path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            known_users.set(_known_users(conn))
            words_total.set(_count(conn, "words"))
            words_max_per_user.set(_max_words_for_user(conn))
            reminders_total.set(_count(conn, "reminders"))
            for source in ("quiz", "learn"):
                quiz_answers_total.labels(source=source).set(_quiz_history_count(conn, source))
            due_review_words.set(_due_review_words(conn))
            learning_queue_words.set(_learning_queue_words(conn))
    except sqlite3.Error:
        # Keep the exporter alive. Prometheus will show stale/flat metrics until the
        # next successful read; bot logs carry the detailed application errors.
        return


def _set_empty_db_metrics() -> None:
    known_users.set(0)
    words_total.set(0)
    words_max_per_user.set(0)
    reminders_total.set(0)
    due_review_words.set(0)
    learning_queue_words.set(0)
    for source in ("quiz", "learn"):
        quiz_answers_total.labels(source=source).set(0)


def _known_users(conn: sqlite3.Connection) -> int:
    row = conn.execute(
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
    ).fetchone()
    return row["cnt"] or 0


def _count(conn: sqlite3.Connection, table: str) -> int:
    if table not in {"words", "reminders"}:
        raise ValueError(f"Unsupported table: {table}")
    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()  # noqa: S608
    return row["cnt"] or 0


def _max_words_for_user(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(cnt), 0) AS cnt
        FROM (
            SELECT COUNT(*) AS cnt
            FROM words
            GROUP BY user_id
        )
        """
    ).fetchone()
    return row["cnt"] or 0


def _quiz_history_count(conn: sqlite3.Connection, source: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM quiz_history WHERE source = ?",
        (source,),
    ).fetchone()
    return row["cnt"] or 0


def _due_review_words(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM words w
        JOIN sm2_state s ON s.word_id = w.id
            AND s.user_id = w.user_id
            AND s.quiz_type = 'word'
        WHERE (s.next_review IS NULL OR s.next_review <= CURRENT_TIMESTAMP)
          AND EXISTS (
            SELECT 1 FROM quiz_history h
            WHERE h.word_id = w.id AND h.user_id = w.user_id
          )
          AND COALESCE(s.last_quality, -1) != 0
        """
    ).fetchone()
    return row["cnt"] or 0


def _learning_queue_words(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM words w
        WHERE NOT EXISTS (
            SELECT 1 FROM quiz_history h
            WHERE h.word_id = w.id AND h.user_id = w.user_id
        )
        OR EXISTS (
            SELECT 1 FROM sm2_state s
            WHERE s.word_id = w.id
              AND s.user_id = w.user_id
              AND s.quiz_type = 'word'
              AND s.last_quality = 0
        )
        """
    ).fetchone()
    return row["cnt"] or 0


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _count_log_levels_today(log_path: str) -> tuple[int, int]:
    today = time.strftime("%Y-%m-%d")
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


if __name__ == "__main__":
    main()
