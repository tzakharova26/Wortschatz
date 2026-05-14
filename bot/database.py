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
    source TEXT NOT NULL DEFAULT 'quiz',
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

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    language TEXT NOT NULL DEFAULT 'en',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

VALID_PARTS_OF_SPEECH = {"n", "v", "adj", "adv", "prep"}
VALID_QUIZ_TYPES = {
    "translate",
    "multiple_choice",
    "article",
    "verb_forms",
    "plural",
    "partizip",
}
WORD_REVIEW_STATE = "word"
VALID_SM2_TYPES = VALID_QUIZ_TYPES | {WORD_REVIEW_STATE}

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
PARTIZIP_QUIZ = "partizip"


def get_quiz_types_for_word(word: dict) -> list[str]:
    """Return the list of applicable quiz types for a given word."""
    pos = word["part_of_speech"]
    types = list(APPLICABLE_QUIZ_TYPES.get(pos, ["translate", "multiple_choice"]))
    if pos == "v":
        partizip = word.get("partizip_ii")
        if partizip and partizip.strip():
            types.append(PARTIZIP_QUIZ)
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
    cursor = await conn.execute("PRAGMA table_info(quiz_history)")
    history_cols = {row[1] for row in await cursor.fetchall()}
    if "source" not in history_cols:
        await conn.execute(
            "ALTER TABLE quiz_history ADD COLUMN source TEXT NOT NULL DEFAULT 'quiz'"
        )
        await conn.execute(
            """UPDATE quiz_history
               SET source = 'learn'
               WHERE correct = 1
                 AND answered_at = (
                   SELECT MIN(h2.answered_at)
                   FROM quiz_history h2
                   WHERE h2.user_id = quiz_history.user_id
                     AND h2.word_id = quiz_history.word_id
                 )"""
        )
        logger.info(
            "Migration: added quiz_history.source column",
            extra={"user_id": "system"},
        )
    await _migrate_word_level_sm2(conn)


async def _migrate_word_level_sm2(conn: aiosqlite.Connection) -> None:
    """Collapse legacy per-quiz SM-2 rows into one canonical row per word.

    Historical quiz_type rows stay in the table for audit/debug compatibility,
    but all runtime scheduling now reads/writes quiz_type='word'.
    """
    await conn.execute(
        """
        INSERT INTO sm2_state (
            user_id, word_id, quiz_type, easiness_factor, interval, repetitions,
            correct_count, next_review, last_quality
        )
        SELECT
            user_id,
            word_id,
            ?,
            AVG(easiness_factor),
            MAX(interval),
            MAX(repetitions),
            MAX(correct_count),
            MIN(next_review),
            MIN(last_quality)
        FROM sm2_state legacy
        WHERE quiz_type != ?
          AND NOT EXISTS (
            SELECT 1 FROM sm2_state current
            WHERE current.user_id = legacy.user_id
              AND current.word_id = legacy.word_id
              AND current.quiz_type = ?
        )
        GROUP BY user_id, word_id
        """,
        (WORD_REVIEW_STATE, WORD_REVIEW_STATE, WORD_REVIEW_STATE),
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


async def count_words(conn: aiosqlite.Connection, user_id: int) -> int:
    cursor = await conn.execute("SELECT COUNT(*) AS cnt FROM words WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    return row["cnt"] or 0


async def count_known_users(conn: aiosqlite.Connection) -> int:
    """Count distinct users that have persisted data in any user-owned table."""
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


async def user_has_persisted_data(conn: aiosqlite.Connection, user_id: int) -> bool:
    cursor = await conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM words WHERE user_id = ?
            UNION
            SELECT 1 FROM sm2_state WHERE user_id = ?
            UNION
            SELECT 1 FROM quiz_history WHERE user_id = ?
            UNION
            SELECT 1 FROM reminders WHERE user_id = ?
            UNION
            SELECT 1 FROM user_settings WHERE user_id = ?
        ) AS exists_flag
        """,
        (user_id, user_id, user_id, user_id, user_id),
    )
    row = await cursor.fetchone()
    return bool(row["exists_flag"])


async def get_user_language(conn: aiosqlite.Connection, user_id: int) -> str:
    cursor = await conn.execute(
        "SELECT language FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return "en"
    return row["language"] or "en"


async def set_user_language(conn: aiosqlite.Connection, user_id: int, language: str) -> None:
    if language not in {"en", "ru"}:
        raise ValueError("language must be 'en' or 'ru'")
    await conn.execute(
        """INSERT INTO user_settings (user_id, language, updated_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id)
           DO UPDATE SET language = excluded.language, updated_at = CURRENT_TIMESTAMP""",
        (user_id, language),
    )
    await conn.commit()
    log_user_action(logger, user_id, f"Language set to {language}")


async def count_user_tags(conn: aiosqlite.Connection, user_id: int) -> int:
    cursor = await conn.execute(
        "SELECT tags FROM words WHERE user_id = ? AND tags != ''",
        (user_id,),
    )
    rows = await cursor.fetchall()
    tag_set: set[str] = set()
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                tag_set.add(tag)
    return len(tag_set)


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


async def count_reminders(conn: aiosqlite.Connection, user_id: int) -> int:
    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM reminders WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    return row["cnt"] or 0


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
    if quiz_type in VALID_QUIZ_TYPES:
        quiz_type = WORD_REVIEW_STATE
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
    if quiz_type in VALID_QUIZ_TYPES:
        quiz_type = WORD_REVIEW_STATE
    if quiz_type not in VALID_SM2_TYPES:
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
      WHERE sb.word_id = w.id
        AND sb.user_id = w.user_id
        AND sb.quiz_type = 'word'
        AND sb.last_quality = 0
    )
"""

_NEEDS_LEARNING_CLAUSE = f"NOT ({_NOT_LEARNING_CLAUSE})"


async def get_due_words(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int = 7,
    tag: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Get words due for review. Returns words with earliest due next_review first.

    Excludes words in the "needs learning" pool (no quiz history yet, or last
    answer was Blackout) — those belong to /learn.
    """
    if now is None:
        now = datetime.now()
    now_str = now.isoformat()

    # Note: f-strings here only interpolate the module-level _NOT_LEARNING_CLAUSE
    # constant, never user input. The S608 lint is a false positive on this shape.
    if tag:
        escaped_tag = _escape_like(tag)
        query = f"""
            SELECT w.*,
                   s.next_review as earliest_review
            FROM words w
            JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
                 AND s.quiz_type = ?
                 AND (s.next_review IS NULL OR s.next_review <= ?)
            WHERE w.user_id = ?
              AND (',' || w.tags || ',') LIKE ? ESCAPE '\\'
              AND {_NOT_LEARNING_CLAUSE}
            ORDER BY earliest_review ASC
            LIMIT ?
        """  # noqa: S608
        cursor = await conn.execute(
            query, (WORD_REVIEW_STATE, now_str, user_id, f"%,{escaped_tag},%", limit)
        )
    else:
        query = f"""
            SELECT w.*,
                   s.next_review as earliest_review
            FROM words w
            JOIN sm2_state s ON w.id = s.word_id AND s.user_id = w.user_id
                 AND s.quiz_type = ?
                 AND (s.next_review IS NULL OR s.next_review <= ?)
            WHERE w.user_id = ?
              AND {_NOT_LEARNING_CLAUSE}
            ORDER BY earliest_review ASC
            LIMIT ?
        """  # noqa: S608
        cursor = await conn.execute(query, (WORD_REVIEW_STATE, now_str, user_id, limit))

    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_needs_learning_words(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int | None = None,
    tag: str | None = None,
    word_ids: list[int] | None = None,
    learning_status: str | None = None,
) -> list[dict]:
    """Words eligible for /learn: never quizzed yet, or any SM-2 row has last_quality=0
    (Blackout demotes a word back into the learning pool).

    Most-recently-added first.
    """
    if learning_status not in {None, "new", "blackout"}:
        raise ValueError(f"Invalid learning_status: {learning_status!r}")

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

    if learning_status == "new":
        where.append(
            """NOT EXISTS (
              SELECT 1 FROM quiz_history hn
              WHERE hn.word_id = w.id AND hn.user_id = w.user_id
            )"""
        )
        where.append(
            """NOT EXISTS (
              SELECT 1 FROM sm2_state sn
              WHERE sn.word_id = w.id
                AND sn.user_id = w.user_id
                AND sn.quiz_type = 'word'
                AND sn.last_quality = 0
            )"""
        )
    elif learning_status == "blackout":
        where.append(
            """EXISTS (
              SELECT 1 FROM sm2_state sb
              WHERE sb.word_id = w.id
                AND sb.user_id = w.user_id
                AND sb.quiz_type = 'word'
                AND sb.last_quality = 0
            )"""
        )

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


async def get_learning_overview(
    conn: aiosqlite.Connection,
    user_id: int,
    tag: str | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Return compact counts for user-facing progress messages.

    - due_review: graduated words with at least one SM-2 quiz type due now
    - needs_learning: new or Blackout-demoted words that belong in /learn
    - review_words: graduated words eligible for /quiz
    - total_words: all saved words in scope
    """
    if now is None:
        now = datetime.now()
    now_str = now.isoformat()

    where = ["w.user_id = ?"]
    params: list = [user_id]
    if tag:
        escaped_tag = _escape_like(tag)
        where.append("(',' || w.tags || ',') LIKE ? ESCAPE '\\'")
        params.append(f"%,{escaped_tag},%")
    scope = " AND ".join(where)

    query = f"""
        SELECT
          COUNT(*) AS total_words,
          SUM(CASE WHEN {_NEEDS_LEARNING_CLAUSE} THEN 1 ELSE 0 END) AS needs_learning,
          SUM(CASE WHEN {_NOT_LEARNING_CLAUSE} THEN 1 ELSE 0 END) AS review_words,
          SUM(CASE WHEN {_NOT_LEARNING_CLAUSE}
                    AND EXISTS (
                      SELECT 1 FROM sm2_state sd
                      WHERE sd.word_id = w.id
                        AND sd.user_id = w.user_id
                        AND sd.quiz_type = 'word'
                        AND (sd.next_review IS NULL OR sd.next_review <= ?)
                    )
                   THEN 1 ELSE 0 END) AS due_review
        FROM words w
        WHERE {scope}
    """  # noqa: S608
    cursor = await conn.execute(query, (now_str, *params))
    row = await cursor.fetchone()
    return {
        "total_words": row["total_words"] or 0,
        "needs_learning": row["needs_learning"] or 0,
        "review_words": row["review_words"] or 0,
        "due_review": row["due_review"] or 0,
    }


# --- Quiz History ---


async def add_quiz_history(
    conn: aiosqlite.Connection,
    user_id: int,
    word_id: int,
    quiz_type: str,
    correct: bool,
    source: str = "quiz",
    commit: bool = True,
) -> None:
    """Append one quiz_history row.

    Pass ``commit=False`` from bulk-apply loops; see ``upsert_sm2_state`` for
    the same pattern.
    """
    if quiz_type not in VALID_QUIZ_TYPES:
        raise ValueError(f"Invalid quiz_type: {quiz_type!r}")
    if source not in {"quiz", "learn"}:
        raise ValueError(f"Invalid quiz history source: {source!r}")

    await conn.execute(
        """INSERT INTO quiz_history (user_id, word_id, quiz_type, correct, source)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, word_id, quiz_type, 1 if correct else 0, source),
    )
    if commit:
        await conn.commit()
    log_user_action(
        logger,
        user_id,
        f"Quiz answer: word_id={word_id}, type={quiz_type}, correct={correct}, source={source}",
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
        """SELECT COUNT(*) as cnt
           FROM quiz_history
           WHERE user_id = ? AND answered_at >= ? AND source = 'quiz'""",
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

    # Words learned IN PERIOD: in user-facing stats, "learned" means the word
    # graduated from /learn into the normal /quiz pool. Graduation writes the
    # word's first quiz_history rows, so the earliest history timestamp is the
    # durable marker we currently have.
    cursor = await conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM (
               SELECT h.word_id, MIN(h.answered_at) AS learned_at
               FROM quiz_history h
               JOIN words w ON w.id = h.word_id AND w.user_id = h.user_id
               WHERE h.user_id = ? AND h.source = 'learn'
                 AND NOT EXISTS (
                   SELECT 1 FROM sm2_state s
                   WHERE s.word_id = w.id
                     AND s.user_id = w.user_id
                     AND s.quiz_type = 'word'
                     AND s.last_quality = 0
                 )
               GROUP BY h.word_id
               HAVING learned_at >= ?
           ) learned""",
        (user_id, since_str),
    )
    row = await cursor.fetchone()
    words_learned = row["cnt"]

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
