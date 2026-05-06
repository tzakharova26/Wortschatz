import json
from datetime import datetime, timezone

import aiosqlite

from bot.logging_config import get_logger, log_user_action, log_user_warning

DB_PATH = "data/wortschatz.db"

logger = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    part_of_speech TEXT NOT NULL,
    german TEXT NOT NULL,
    article TEXT,
    plural TEXT,
    partizip_ii TEXT,
    irregular_forms TEXT,
    translation TEXT NOT NULL,
    tags TEXT DEFAULT '',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_words_user_id ON words(user_id);
CREATE INDEX IF NOT EXISTS idx_words_user_pos ON words(user_id, part_of_speech);

CREATE TABLE IF NOT EXISTS sm2_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    quiz_type TEXT NOT NULL,
    easiness_factor REAL DEFAULT 2.5,
    interval INTEGER DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    next_review TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(user_id, word_id, quiz_type)
);

CREATE INDEX IF NOT EXISTS idx_sm2_word_id ON sm2_state(word_id);
CREATE INDEX IF NOT EXISTS idx_sm2_user_next ON sm2_state(user_id, next_review);

CREATE TABLE IF NOT EXISTS quiz_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    quiz_type TEXT NOT NULL,
    correct INTEGER NOT NULL,
    answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_user_date ON quiz_history(user_id, answered_at);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    hour INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id);
"""

VALID_PARTS_OF_SPEECH = {"n", "v", "adj", "adv", "prep"}
VALID_QUIZ_TYPES = {"translate", "multiple_choice", "article", "verb_forms"}

# Mapping: part_of_speech -> list of applicable quiz types
APPLICABLE_QUIZ_TYPES: dict[str, list[str]] = {
    "n": ["translate", "multiple_choice", "article"],
    "v": ["translate", "multiple_choice"],  # regular verbs
    "adj": ["translate", "multiple_choice"],
    "adv": ["translate", "multiple_choice"],
    "prep": ["translate", "multiple_choice"],
}

# Irregular verbs (those with ich/du/er forms) also get "verb_forms"
VERB_FORMS_QUIZ = "verb_forms"


def get_quiz_types_for_word(word: dict) -> list[str]:
    """Return the list of applicable quiz types for a given word."""
    pos = word["part_of_speech"]
    types = list(APPLICABLE_QUIZ_TYPES.get(pos, ["translate", "multiple_choice"]))
    if pos == "v":
        forms = parse_irregular_forms(word.get("irregular_forms"))
        if forms:
            types.append(VERB_FORMS_QUIZ)
    return types


def parse_irregular_forms(raw: str | None) -> dict | None:
    """Parse irregular_forms JSON string from DB into a dict."""
    if not raw:
        return None
    try:
        forms = json.loads(raw)
        if isinstance(forms, dict):
            return forms
        logger.warning(
            "irregular_forms is not a dict: %r",
            raw,
            extra={"user_id": "system"},
        )
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Failed to parse irregular_forms JSON: %r",
            raw,
            extra={"user_id": "system"},
        )
    return None


def _escape_like(value: str) -> str:
    """Escape special LIKE characters in a value."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_tags(tags: str) -> str:
    """Normalize a comma-separated tags string: strip whitespace, remove empties."""
    parts = [t.strip() for t in tags.split(",") if t.strip()]
    return ",".join(parts)


async def get_connection(db_path: str = DB_PATH) -> aiosqlite.Connection:
    try:
        conn = await aiosqlite.connect(db_path)
    except Exception:
        logger.error(
            "Failed to connect to database at %s",
            db_path,
            extra={"user_id": "system"},
            exc_info=True,
        )
        raise
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db(db_path: str = DB_PATH) -> None:
    conn = None
    try:
        conn = await get_connection(db_path)
        await conn.executescript(SCHEMA)
        await conn.commit()
        logger.info("Database initialized", extra={"user_id": "system"})
    except Exception:
        logger.error("Failed to initialize database", extra={"user_id": "system"}, exc_info=True)
        raise
    finally:
        if conn is not None:
            await conn.close()


# --- Words ---


async def add_word(
    conn: aiosqlite.Connection,
    user_id: int,
    part_of_speech: str,
    german: str,
    translation: str,
    article: str | None = None,
    plural: str | None = None,
    partizip_ii: str | None = None,
    irregular_forms: dict | None = None,
    tags: str = "",
) -> int:
    if part_of_speech not in VALID_PARTS_OF_SPEECH:
        raise ValueError(f"Invalid part_of_speech: {part_of_speech!r}")
    if not german or not german.strip():
        raise ValueError("german word cannot be empty")
    if not translation or not translation.strip():
        raise ValueError("translation cannot be empty")

    normalized_tags = _normalize_tags(tags)
    cursor = await conn.execute(
        """INSERT INTO words
           (user_id, part_of_speech, german, article, plural,
            partizip_ii, irregular_forms, translation, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            part_of_speech,
            german.strip(),
            article,
            plural,
            partizip_ii,
            json.dumps(irregular_forms) if irregular_forms is not None else None,
            translation.strip(),
            normalized_tags,
        ),
    )
    await conn.commit()
    safe_german = "".join(ch if ch.isprintable() else "?" for ch in german.strip())[:100]
    log_user_action(logger, user_id, f"Added word: {safe_german} ({part_of_speech})")
    return cursor.lastrowid


async def delete_word(conn: aiosqlite.Connection, user_id: int, word_id: int) -> bool:
    cursor = await conn.execute(
        "DELETE FROM words WHERE id = ? AND user_id = ?",
        (word_id, user_id),
    )
    await conn.commit()
    if cursor.rowcount > 0:
        log_user_action(logger, user_id, f"Deleted word id={word_id}")
        return True
    log_user_warning(logger, user_id, f"Attempted to delete non-existent word id={word_id}")
    return False


async def get_words(conn: aiosqlite.Connection, user_id: int, tag: str | None = None) -> list[dict]:
    if tag:
        escaped_tag = _escape_like(tag)
        cursor = await conn.execute(
            """SELECT * FROM words WHERE user_id = ?
               AND (',' || tags || ',') LIKE ? ESCAPE '\\'
               ORDER BY added_at DESC""",
            (user_id, f"%,{escaped_tag},%"),
        )
    else:
        cursor = await conn.execute(
            "SELECT * FROM words WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_word_by_id(conn: aiosqlite.Connection, word_id: int, user_id: int) -> dict | None:
    cursor = await conn.execute(
        "SELECT * FROM words WHERE id = ? AND user_id = ?", (word_id, user_id)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def find_words_by_german(conn: aiosqlite.Connection, user_id: int, german: str) -> list[dict]:
    """Find words by german text (case-insensitive)."""
    cursor = await conn.execute(
        "SELECT * FROM words WHERE user_id = ? AND LOWER(german) = LOWER(?)",
        (user_id, german.strip()),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def find_word_by_german_pos(
    conn: aiosqlite.Connection, user_id: int, german: str, part_of_speech: str
) -> dict | None:
    """Find a single word by german text + POS (case-insensitive). Used by tag merge."""
    cursor = await conn.execute(
        """SELECT * FROM words
           WHERE user_id = ? AND LOWER(german) = LOWER(?) AND part_of_speech = ?""",
        (user_id, german.strip(), part_of_speech),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_word_tags(
    conn: aiosqlite.Connection, user_id: int, word_id: int, new_tags: str
) -> None:
    """Replace the tags column for a word. Caller is responsible for the merged value."""
    await conn.execute(
        "UPDATE words SET tags = ? WHERE id = ? AND user_id = ?",
        (new_tags, word_id, user_id),
    )
    await conn.commit()
    log_user_action(logger, user_id, f"Updated tags on word id={word_id}: '{new_tags}'")


def merge_tag(existing_tags: str, new_tag: str) -> tuple[str, bool]:
    """Add `new_tag` to the comma-separated `existing_tags`, dedup.

    Returns (merged_tags, changed). `changed` is False if the tag was already present
    or if `new_tag` is empty/whitespace.
    """
    new_tag = new_tag.strip()
    if not new_tag:
        return existing_tags, False
    existing = [t.strip() for t in existing_tags.split(",") if t.strip()]
    if new_tag in existing:
        return existing_tags, False
    existing.append(new_tag)
    return ",".join(existing), True


async def get_tags(conn: aiosqlite.Connection, user_id: int) -> list[str]:
    cursor = await conn.execute(
        "SELECT DISTINCT tags FROM words WHERE user_id = ? AND tags != ''",
        (user_id,),
    )
    rows = await cursor.fetchall()
    tag_set = set()
    for row in rows:
        for t in row["tags"].split(","):
            t = t.strip()
            if t:
                tag_set.add(t)
    return sorted(tag_set)


# --- Words by part of speech (for quiz options) ---


async def get_words_by_pos(
    conn: aiosqlite.Connection, user_id: int, part_of_speech: str
) -> list[dict]:
    cursor = await conn.execute(
        "SELECT * FROM words WHERE user_id = ? AND part_of_speech = ?",
        (user_id, part_of_speech),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- SM2 State ---


async def get_sm2_state(
    conn: aiosqlite.Connection, user_id: int, word_id: int, quiz_type: str
) -> dict | None:
    cursor = await conn.execute(
        """SELECT * FROM sm2_state
           WHERE user_id = ? AND word_id = ? AND quiz_type = ?""",
        (user_id, word_id, quiz_type),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_sm2_state(
    conn: aiosqlite.Connection,
    user_id: int,
    word_id: int,
    quiz_type: str,
    easiness_factor: float,
    interval: int,
    repetitions: int,
    correct_count: int,
    next_review: datetime,
) -> None:
    if quiz_type not in VALID_QUIZ_TYPES:
        raise ValueError(f"Invalid quiz_type: {quiz_type!r}")

    await conn.execute(
        """INSERT INTO sm2_state
           (user_id, word_id, quiz_type, easiness_factor, interval, repetitions,
            correct_count, next_review)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, word_id, quiz_type)
           DO UPDATE SET
             easiness_factor = excluded.easiness_factor,
             interval = excluded.interval,
             repetitions = excluded.repetitions,
             correct_count = excluded.correct_count,
             next_review = excluded.next_review""",
        (
            user_id,
            word_id,
            quiz_type,
            easiness_factor,
            interval,
            repetitions,
            correct_count,
            next_review.isoformat(),
        ),
    )
    await conn.commit()
    log_user_action(
        logger,
        user_id,
        f"Updated SM2 state: word_id={word_id}, type={quiz_type}, "
        f"ef={easiness_factor:.2f}, interval={interval}, reps={repetitions}",
    )


async def get_due_words(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int = 7,
    tag: str | None = None,
) -> list[dict]:
    """Get words most due for review. Returns words with earliest next_review first.

    Words without SM2 state (never reviewed) are prioritized.
    """
    if tag:
        escaped_tag = _escape_like(tag)
        query = """
            SELECT w.*, MIN(COALESCE(s.next_review, '1970-01-01')) as earliest_review
            FROM words w
            LEFT JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
            WHERE w.user_id = ?
              AND (',' || w.tags || ',') LIKE ? ESCAPE '\\'
            GROUP BY w.id
            ORDER BY earliest_review ASC
            LIMIT ?
        """
        cursor = await conn.execute(query, (user_id, f"%,{escaped_tag},%", limit))
    else:
        query = """
            SELECT w.*, MIN(COALESCE(s.next_review, '1970-01-01')) as earliest_review
            FROM words w
            LEFT JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
            WHERE w.user_id = ?
            GROUP BY w.id
            ORDER BY earliest_review ASC
            LIMIT ?
        """
        cursor = await conn.execute(query, (user_id, limit))

    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- Quiz History ---


async def add_quiz_history(
    conn: aiosqlite.Connection,
    user_id: int,
    word_id: int,
    quiz_type: str,
    correct: bool,
) -> None:
    if quiz_type not in VALID_QUIZ_TYPES:
        raise ValueError(f"Invalid quiz_type: {quiz_type!r}")

    await conn.execute(
        """INSERT INTO quiz_history (user_id, word_id, quiz_type, correct)
           VALUES (?, ?, ?, ?)""",
        (user_id, word_id, quiz_type, 1 if correct else 0),
    )
    await conn.commit()
    log_user_action(
        logger,
        user_id,
        f"Quiz answer: word_id={word_id}, type={quiz_type}, correct={correct}",
    )


async def get_stats(conn: aiosqlite.Connection, user_id: int, since: datetime) -> dict:
    """Get statistics since a given date.

    `since` is interpreted as local time (matching `datetime.now()` callers); it is
    converted to UTC for comparison against SQLite's CURRENT_TIMESTAMP values.
    """
    # SQLite CURRENT_TIMESTAMP returns UTC formatted as "YYYY-MM-DD HH:MM:SS".
    # Match that format so string comparison aligns (T vs space ordering would otherwise
    # break same-date comparisons).
    if since.tzinfo is not None:
        since_utc = since.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        # Naive: treat as local, convert to UTC to match what the DB stores.
        since_utc = since.astimezone(timezone.utc).replace(tzinfo=None)
    since_str = since_utc.strftime("%Y-%m-%d %H:%M:%S")

    # Quizzes completed
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM quiz_history WHERE user_id = ? AND answered_at >= ?",
        (user_id, since_str),
    )
    row = await cursor.fetchone()
    quizzes_completed = row["cnt"]

    # Words added
    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM words WHERE user_id = ? AND added_at >= ?",
        (user_id, since_str),
    )
    row = await cursor.fetchone()
    words_added = row["cnt"]

    # Words learned IN PERIOD: count words that crossed the learned threshold during [since, now].
    # A word is learned when all applicable quiz_types have >= 4 correct answers; the moment
    # of becoming learned is the timestamp of the LAST such qualifying answer (across the
    # quiz_types). Count those whose "learned at" timestamp falls within the period.
    cursor = await conn.execute(
        """SELECT w.id, w.part_of_speech, w.irregular_forms
           FROM words w
           WHERE w.user_id = ?""",
        (user_id,),
    )
    candidate_rows = await cursor.fetchall()
    words_learned = 0
    for r in candidate_rows:
        word_dict = dict(r)
        applicable = get_quiz_types_for_word(word_dict)
        # For each applicable quiz_type, find the timestamp of the 4th correct answer.
        # If any quiz_type doesn't have 4 correct answers, the word isn't learned yet.
        type_timestamps = []
        all_done = True
        for qt in applicable:
            qt_cursor = await conn.execute(
                """SELECT answered_at FROM quiz_history
                   WHERE user_id = ? AND word_id = ? AND quiz_type = ? AND correct = 1
                   ORDER BY answered_at LIMIT 1 OFFSET 3""",
                (user_id, word_dict["id"], qt),
            )
            qt_row = await qt_cursor.fetchone()
            if qt_row is None:
                all_done = False
                break
            type_timestamps.append(qt_row[0])
        if not all_done:
            continue
        # Word became learned at the latest of these "4th-correct" timestamps
        learned_at = max(type_timestamps)
        if learned_at >= since_str:
            words_learned += 1

    return {
        "quizzes_completed": quizzes_completed,
        "words_added": words_added,
        "words_learned": words_learned,
    }


# --- Reminders ---


async def add_reminder(
    conn: aiosqlite.Connection,
    user_id: int,
    hour: int,
    minute: int,
    tz: str = "Europe/Berlin",
) -> int:
    """Insert a new reminder. Returns its id."""
    if not (0 <= hour < 24):
        raise ValueError(f"hour must be 0-23, got {hour}")
    if not (0 <= minute < 60):
        raise ValueError(f"minute must be 0-59, got {minute}")
    cursor = await conn.execute(
        "INSERT INTO reminders (user_id, hour, minute, timezone) VALUES (?, ?, ?, ?)",
        (user_id, hour, minute, tz),
    )
    await conn.commit()
    log_user_action(logger, user_id, f"Added reminder {hour:02d}:{minute:02d} {tz}")
    return cursor.lastrowid


async def get_reminders(conn: aiosqlite.Connection, user_id: int) -> list[dict]:
    """Return all reminders for the given user, ordered by hour/minute."""
    cursor = await conn.execute(
        "SELECT * FROM reminders WHERE user_id = ? ORDER BY hour, minute",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def delete_reminder(conn: aiosqlite.Connection, user_id: int, reminder_id: int) -> bool:
    cursor = await conn.execute(
        "DELETE FROM reminders WHERE id = ? AND user_id = ?",
        (reminder_id, user_id),
    )
    await conn.commit()
    if cursor.rowcount > 0:
        log_user_action(logger, user_id, f"Deleted reminder id={reminder_id}")
        return True
    log_user_warning(logger, user_id, f"Tried to delete non-existent reminder id={reminder_id}")
    return False


async def delete_all_reminders(conn: aiosqlite.Connection, user_id: int) -> int:
    cursor = await conn.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
    await conn.commit()
    log_user_action(logger, user_id, f"Deleted all reminders ({cursor.rowcount} rows)")
    return cursor.rowcount


async def get_all_reminders(conn: aiosqlite.Connection) -> list[dict]:
    """Return reminders for all users — used at bot startup to repopulate JobQueue."""
    cursor = await conn.execute("SELECT * FROM reminders")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
