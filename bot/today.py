from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import aiosqlite

from bot.config import LIST_MAX_WORDS
from bot.database import get_words_practiced_between
from bot.i18n import normalize_language
from bot.reminders import DEFAULT_TZ

_TODAY_TZ = ZoneInfo(DEFAULT_TZ)


async def get_today_progress(conn: aiosqlite.Connection, user_id: int, lang: str = "en") -> str:
    """Format today's learned/repeated word cards for AI-assisted follow-up practice."""
    lang = normalize_language(lang)
    now_local = datetime.now(_TODAY_TZ)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    learned = await get_words_practiced_between(
        conn, user_id, start, end, source="learn", limit=LIST_MAX_WORDS
    )
    repeated = await get_words_practiced_between(
        conn, user_id, start, end, source="quiz", limit=LIST_MAX_WORDS
    )

    if lang == "ru":
        lines = [
            "<b>Сегодняшний прогресс</b>",
            "",
            "<b>Выучено сегодня:</b>",
            *_format_word_lines(learned, empty="Пока нет слов из /learn."),
            "",
            "<b>Повторено сегодня:</b>",
            *_format_word_lines(repeated, empty="Пока нет слов из /quiz или /verbs."),
            "",
            "Можно отправить этот список в AI и попросить примеры, мини-диалог "
            "или дополнительные вопросы.",
        ]
    else:
        lines = [
            "<b>Today's Progress</b>",
            "",
            "<b>Learned today:</b>",
            *_format_word_lines(learned, empty="No /learn words yet today."),
            "",
            "<b>Repeated today:</b>",
            *_format_word_lines(repeated, empty="No /quiz or /verbs words yet today."),
            "",
            "You can send this list to an AI and ask for examples, a mini-dialogue, "
            "or extra questions.",
        ]
    return "\n".join(lines)


def _format_word_lines(words: list[dict], empty: str) -> list[str]:
    if not words:
        return [f"  {empty}"]
    lines = []
    for word in words:
        lines.append(f"  - {_card_text(word)}")
    if len(words) >= LIST_MAX_WORDS:
        lines.append(f"  ...showing first {LIST_MAX_WORDS} cards")
    return lines


def _card_text(word: dict) -> str:
    pos = escape(word.get("part_of_speech") or "?")
    german = escape(word.get("german") or "")
    translation = escape(word.get("translation") or "")
    if pos == "n":
        article = escape(word.get("article") or "?")
        plural = escape(word.get("plural") or "-")
        return f"{article} {german} (pl: {plural}) = {translation}"
    return f"{german} ({pos}) = {translation}"
