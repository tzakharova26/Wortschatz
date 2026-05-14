from __future__ import annotations

import os

import aiosqlite

from bot.config import (
    DB_SIZE_HARD_LIMIT_MB,
    DB_SIZE_WARNING_MB,
    MAX_GERMAN_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_USER,
    MAX_TAGS_PER_WORD,
    MAX_TRANSLATION_LENGTH,
    MAX_USERS,
)
from bot.database import (
    count_known_users,
    count_user_tags,
    user_has_persisted_data,
)
from bot.logging_config import get_logger, log_user_warning

logger = get_logger(__name__)


class LimitExceeded(Exception):
    def __init__(self, user_message: str, log_message: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.log_message = log_message or user_message


def _split_tags(tags: str | None) -> list[str]:
    if not tags:
        return []
    return [tag.strip() for tag in tags.split(",") if tag.strip()]


async def get_db_size_mb(conn: aiosqlite.Connection) -> float:
    """Return main SQLite DB file size. In-memory DBs report 0."""
    cursor = await conn.execute("PRAGMA database_list")
    rows = await cursor.fetchall()
    db_path = ""
    for row in rows:
        # PRAGMA database_list columns: seq, name, file.
        if row[1] == "main":
            db_path = row[2] or ""
            break
    if not db_path or db_path == ":memory:" or not os.path.exists(db_path):
        return 0.0
    return os.path.getsize(db_path) / (1024 * 1024)


async def ensure_db_size_allows_write(conn: aiosqlite.Connection, user_id: int) -> None:
    size_mb = await get_db_size_mb(conn)
    if size_mb >= DB_SIZE_HARD_LIMIT_MB:
        raise LimitExceeded(
            "The bot database is too large right now, so this action was not saved. "
            "Please contact the bot owner.",
            f"DB hard limit exceeded: {size_mb:.1f} MB >= {DB_SIZE_HARD_LIMIT_MB} MB",
        )
    if size_mb >= DB_SIZE_WARNING_MB:
        log_user_warning(
            logger,
            user_id,
            f"DB size warning: {size_mb:.1f} MB >= {DB_SIZE_WARNING_MB} MB",
        )


async def ensure_user_allowed(conn: aiosqlite.Connection, user_id: int) -> None:
    if await user_has_persisted_data(conn, user_id):
        return
    users = await count_known_users(conn)
    if users >= MAX_USERS:
        raise LimitExceeded(
            f"This bot is currently limited to {MAX_USERS} people. "
            "Your data was not saved. Please contact the bot owner.",
            f"Max users exceeded: current={users}, limit={MAX_USERS}",
        )


def validate_single_tag(tag: str | None) -> None:
    if not tag:
        return
    if len(tag) > MAX_TAG_LENGTH:
        raise LimitExceeded(
            f"Tag is too long ({len(tag)} characters). Maximum tag length is "
            f"{MAX_TAG_LENGTH}. Nothing was saved.",
            f"Tag length exceeded: len={len(tag)}, limit={MAX_TAG_LENGTH}",
        )


async def ensure_user_tag_capacity(
    conn: aiosqlite.Connection, user_id: int, existing_tags: set[str], new_tag: str | None
) -> None:
    if not new_tag or new_tag in existing_tags:
        return
    current_count = await count_user_tags(conn, user_id)
    if current_count >= MAX_TAGS_PER_USER:
        raise LimitExceeded(
            f"You already have {current_count} tags. The limit is {MAX_TAGS_PER_USER}, "
            "so this batch was not saved.",
            f"Max tags per user exceeded: current={current_count}, limit={MAX_TAGS_PER_USER}",
        )


def validate_word_lengths(word: dict) -> None:
    fields = [
        ("German word", word.get("german") or "", MAX_GERMAN_LENGTH),
        ("Translation", word.get("translation") or "", MAX_TRANSLATION_LENGTH),
        ("Plural", word.get("plural") or "", MAX_GERMAN_LENGTH),
        ("Partizip II", word.get("partizip_ii") or "", MAX_GERMAN_LENGTH),
    ]
    forms = word.get("irregular_forms") or {}
    if isinstance(forms, dict):
        fields.extend(
            (f"{key} form", value or "", MAX_GERMAN_LENGTH) for key, value in forms.items()
        )

    for label, value, limit in fields:
        if len(value) > limit:
            raise LimitExceeded(
                f"{label} is too long ({len(value)} characters). Maximum is {limit}. "
                "Nothing was saved.",
                f"{label} length exceeded: len={len(value)}, limit={limit}",
            )


def validate_tags_per_word(existing_tags: str, new_tag: str | None) -> None:
    tags = _split_tags(existing_tags)
    if new_tag and new_tag not in tags:
        tags.append(new_tag)
    if len(tags) > MAX_TAGS_PER_WORD:
        raise LimitExceeded(
            f"This word would have {len(tags)} tags. The limit is {MAX_TAGS_PER_WORD} "
            "tags per word, so nothing was saved.",
            f"Max tags per word exceeded: count={len(tags)}, limit={MAX_TAGS_PER_WORD}",
        )
