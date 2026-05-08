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
    last_quality INTEGER,
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
VALID_QUIZ_TYPES = {"translate", "multiple_choice", "article", "verb_forms", "plural"}

# Mapping: part_of_speech -> list of applicable quiz types (always-applicable ones).
# Per-word extras (verb_forms for irregular verbs, plural for nouns that actually
# have a plural form) are added in get_quiz_types_for_word.
APPLICABLE_QUIZ_TYPES: dict[str, list[str]] = {
    "n": ["translate", "multiple_choice", "article"],
    "v": ["translate", "multiple_choice"],  # regular verbs
    "adj": ["translate", "multiple_choice"],
    "adv": ["translate", "multiple_choice"],
    "prep": ["translate", "multiple_choice"],
}

# Irregular verbs (those with ich/du/er forms) also get "verb_forms"
VERB_FORMS_QUIZ = "verb_forms"
PLURAL_QUIZ = "plural"


def get_quiz_types_for_word(word: dict) -> list[str]:
    """Return the list of applicable quiz types for a given word."""
    pos = word["part_of_speech"]
    types = list(APPLICABLE_QUIZ_TYPES.get(pos, ["translate", "multiple_choice"]))
    if pos == "v":
        forms = parse_irregular_forms(word.get("irregular_forms"))
        if forms:
            types.append(VERB_FORMS_QUIZ)
    elif pos == "n":
        plural = word.get("plural")
        if plural and plural.strip():
            types.append(PLURAL_QUIZ)
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
        await _apply_schema(conn)
        logger.info("Database initialized", extra={"user_id": "system"})
    except Exception:
        logger.error("Failed to initialize database", extra={"user_id": "system"}, exc_info=True)
        raise
    finally:
        if conn is not None:
            await conn.close()


async def _apply_schema(conn: aiosqlite.Connection) -> None:
    """Apply SCHEMA + run migrations on an existing connection.

    Extracted so tests can reuse the exact production setup on their own
    in-memory connection — ``init_db(":memory:")`` won't work because the
    in-memory DB dies when ``init_db`` closes its own connection.
    """
    await conn.executescript(SCHEMA)
    await _migrate(conn)
    await conn.commit()


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Idempotent migrations for schema changes that need to be applied to
    pre-existing DBs. Adding a column is safe to run repeatedly because we
    inspect PRAGMA table_info first."""
    cursor = await conn.execute("PRAGMA table_info(sm2_state)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "last_quality" not in cols:
        await conn.execute("ALTER TABLE sm2_state ADD COLUMN last_quality INTEGER")
        logger.info(
            "Migration: added sm2_state.last_quality column",
            extra={"user_id": "system"},
        )


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
    last_quality: int | None = None,
    commit: bool = True,
) -> None:
    """Upsert one SM-2 row.

    Pass ``commit=False`` when calling inside a bulk-apply loop (apply_results,
    apply_graduations) so all rows land in a single transaction; the caller
    issues one commit at the end. Default behaviour preserves the per-row
    commit for ad-hoc callers and tests.
    """
    if quiz_type not in VALID_QUIZ_TYPES:
        raise ValueError(f"Invalid quiz_type: {quiz_type!r}")

    await conn.execute(
        """INSERT INTO sm2_state
           (user_id, word_id, quiz_type, easiness_factor, interval, repetitions,
            correct_count, next_review, last_quality)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, word_id, quiz_type)
           DO UPDATE SET
             easiness_factor = excluded.easiness_factor,
             interval = excluded.interval,
             repetitions = excluded.repetitions,
             correct_count = excluded.correct_count,
             next_review = excluded.next_review,
             last_quality = excluded.last_quality""",
        (
            user_id,
            word_id,
            quiz_type,
            easiness_factor,
            interval,
            repetitions,
            correct_count,
            next_review.isoformat(),
            last_quality,
        ),
    )
    if commit:
        await conn.commit()
    log_user_action(
        logger,
        user_id,
        f"Updated SM2 state: word_id={word_id}, type={quiz_type}, "
        f"ef={easiness_factor:.2f}, interval={interval}, reps={repetitions}, "
        f"last_quality={last_quality}",
    )


_NOT_LEARNING_CLAUSE = """
    EXISTS (
      SELECT 1 FROM quiz_history h
      WHERE h.word_id = w.id AND h.user_id = w.user_id
    )
    AND NOT EXISTS (
      SELECT 1 FROM sm2_state sb
      WHERE sb.word_id = w.id AND sb.user_id = w.user_id AND sb.last_quality = 0
    )
"""

_NEEDS_LEARNING_CLAUSE = f"NOT ({_NOT_LEARNING_CLAUSE})"


async def get_due_words(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int = 7,
    tag: str | None = None,
) -> list[dict]:
    """Get words most due for review. Returns words with earliest next_review first.

    Excludes words in the "needs learning" pool (no quiz history yet, or last
    answer was Blackout) — those belong to /learn.
    """
    # Note: f-strings here only interpolate the module-level _NOT_LEARNING_CLAUSE
    # constant, never user input. The S608 lint is a false positive on this shape.
    if tag:
        escaped_tag = _escape_like(tag)
        query = f"""
            SELECT w.*, MIN(COALESCE(s.next_review, '1970-01-01')) as earliest_review
            FROM words w
            LEFT JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
            WHERE w.user_id = ?
              AND (',' || w.tags || ',') LIKE ? ESCAPE '\\'
              AND {_NOT_LEARNING_CLAUSE}
            GROUP BY w.id
            ORDER BY earliest_review ASC
            LIMIT ?
        """  # noqa: S608
        cursor = await conn.execute(query, (user_id, f"%,{escaped_tag},%", limit))
    else:
        query = f"""
            SELECT w.*, MIN(COALESCE(s.next_review, '1970-01-01')) as earliest_review
            FROM words w
            LEFT JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
            WHERE w.user_id = ?
              AND {_NOT_LEARNING_CLAUSE}
            GROUP BY w.id
            ORDER BY earliest_review ASC
            LIMIT ?
        """  # noqa: S608
        cursor = await conn.execute(query, (user_id, limit))

    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_needs_learning_words(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int | None = None,
    tag: str | None = None,
    word_ids: list[int] | None = None,
) -> list[dict]:
    """Words eligible for /learn: never quizzed yet, or any SM-2 row has last_quality=0
    (Blackout demotes a word back into the learning pool).

    Most-recently-added first.
    """
    where = ["w.user_id = ?", _NEEDS_LEARNING_CLAUSE]
    params: list = [user_id]

    if tag:
        escaped_tag = _escape_like(tag)
        where.append("(',' || w.tags || ',') LIKE ? ESCAPE '\\'")
        params.append(f"%,{escaped_tag},%")

    if word_ids:
        placeholders = ",".join("?" for _ in word_ids)
        where.append(f"w.id IN ({placeholders})")
        params.extend(word_ids)

    # The interpolated pieces (where clauses + IN-placeholders) are constants /
    # `?` placeholders only, no user-supplied SQL. S608 is a false positive here.
    query = f"""
        SELECT w.* FROM words w
        WHERE {" AND ".join(where)}
        ORDER BY w.added_at DESC, w.id DESC
    """  # noqa: S608
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    cursor = await conn.execute(query, tuple(params))
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- Quiz History ---


async def add_quiz_history(
    conn: aiosqlite.Connection,
    user_id: int,
    word_id: int,
    quiz_type: str,
    correct: bool,
    commit: bool = True,
) -> None:
    """Append one quiz_history row.

    Pass ``commit=False`` from bulk-apply loops; see ``upsert_sm2_state`` for
    the same pattern.
    """
    if quiz_type not in VALID_QUIZ_TYPES:
        raise ValueError(f"Invalid quiz_type: {quiz_type!r}")

    await conn.execute(
        """INSERT INTO quiz_history (user_id, word_id, quiz_type, correct)
           VALUES (?, ?, ?, ?)""",
        (user_id, word_id, quiz_type, 1 if correct else 0),
    )
    if commit:
        await conn.commit()
    log_user_action(
        logger,
        user_id,
        f"Quiz answer: word_id={word_id}, type={quiz_type}, correct={correct}",
    )


async def get_stats(conn: aiosqlite.Connection, user_id: int, since: datetime) -> dict:
    """Get statistics since a given date.

    `since` MUST be timezone-aware. SQLite's CURRENT_TIMESTAMP is UTC; we convert
    `since` to UTC and format with a space separator so string comparison against
    DB values works (Python's isoformat() uses 'T', which sorts AFTER space and
    breaks same-date comparisons — past pain).

    Raises ValueError on naive input rather than silently mis-interpreting it.
    """
    if since.tzinfo is None:
        raise ValueError(
            "get_stats requires a timezone-aware datetime; got naive (would be "
            "interpreted as system TZ which differs between Docker UTC and the host)"
        )
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

    # Words learned IN PERIOD: a word "becomes learned" the moment its slowest
    # applicable quiz_type hits its 4th correct answer. Count words whose
    # "learned at" timestamp falls within the period.
    #
    # One window-function query gets the 4th-correct timestamp for every
    # (word, quiz_type) pair across all the user's words. The previous
    # implementation ran an indexed SELECT per (word × quiz_type) — O(N×M)
    # round-trips that scaled poorly past a few hundred words.
    cursor = await conn.execute(
        "SELECT id, part_of_speech, article, plural, irregular_forms "
        "FROM words WHERE user_id = ?",
        (user_id,),
    )
    word_rows = await cursor.fetchall()

    cursor = await conn.execute(
        """SELECT word_id, quiz_type, answered_at AS fourth_at
           FROM (
               SELECT word_id, quiz_type, answered_at,
                      ROW_NUMBER() OVER (
                          PARTITION BY word_id, quiz_type
                          ORDER BY answered_at
                      ) AS rn
               FROM quiz_history
               WHERE user_id = ? AND correct = 1
           ) t
           WHERE rn = 4""",
        (user_id,),
    )
    fourth_rows = await cursor.fetchall()

    fourth_by_word: dict[int, dict[str, str]] = {}
    for r in fourth_rows:
        fourth_by_word.setdefault(r["word_id"], {})[r["quiz_type"]] = r["fourth_at"]

    words_learned = 0
    for r in word_rows:
        word_dict = dict(r)
        applicable = set(get_quiz_types_for_word(word_dict))
        per_type = fourth_by_word.get(word_dict["id"], {})
        if not applicable.issubset(per_type):
            continue
        learned_at = max(per_type[qt] for qt in applicable)
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
