"""Internal helpers shared across the handler submodules.

Anything truly cross-flow lives here: DB-connection access, log sanitization,
the keyboard-stripping helper used by inline-button callbacks, the
ConversationHandler state numbers, all CB_* callback-data prefixes, and the
``_format_word_tables`` formatter used by both /list and /add. Per-flow
helpers (e.g. _rating_keyboard for /quiz) live in their own submodule.
"""

from __future__ import annotations

import html
import time
from typing import Any

from telegram.ext import ContextTypes

from bot.database import parse_irregular_forms
from bot.logging_config import get_logger

logger = get_logger(__name__)


# Lifetimes for short-lived intent stashed on ``context.user_data`` (keys like
# ``pending_delete`` and ``pending_learn_ids``). Without an explicit TTL the
# entries linger until their own success paths consume them — pivoting to an
# unrelated command leaves them behind, and a /delete_confirm hours later
# would silently confirm an old multi-match. ``pending_delete`` is short
# because the confirm is meant to follow immediately; ``pending_learn_ids``
# is longer to accommodate users who add words and tap "Start learning" later.
PENDING_DELETE_TTL_S = 300
PENDING_LEARN_TTL_S = 3600


def pending_set(context: ContextTypes.DEFAULT_TYPE, key: str, value: Any, ttl: int) -> None:
    """Stash a short-lived value on user_data with an expiry stamp."""
    context.user_data[key] = {"value": value, "expires_at": time.monotonic() + ttl}


def pending_pop(context: ContextTypes.DEFAULT_TYPE, key: str) -> Any:
    """Pop a TTL-stamped value if still fresh, else return None and discard.

    Tolerates legacy/raw values (a bare list etc.) by returning them as-is —
    keeps tests that hand-set ``user_data[key] = [...]`` working.
    """
    entry = context.user_data.pop(key, None)
    if entry is None:
        return None
    if isinstance(entry, dict) and "expires_at" in entry:
        if time.monotonic() > entry["expires_at"]:
            return None
        return entry["value"]
    return entry  # raw legacy value


# ConversationHandler states. Each conversation has its own state space so
# values could collide across them harmlessly, but keeping one shared range
# preserves backward compatibility with imports of the form
# ``from bot.handlers import LEARN_ANSWERING``.
ADD_WORDS, ADD_CONFIRM, QUIZ_ANSWERING, QUIZ_RATING, LEARN_ANSWERING = range(5)
CONTACT_WRITING = 5


# Callback data prefixes
CB_HELP = "help:"
CB_MC = "mc:"
CB_ART = "art:"
CB_RATE = "rate:"
CB_ADD = "add:"
CB_LEARN_SHOW = "lshow:"
CB_LEARN_MC = "lmc:"
CB_LEARN_ART = "lart:"
CB_LEARN_BATCH = "lbatch:"  # Post-/add "Start learning" button
CB_OWNER = "owner:"


def _get_conn(context: ContextTypes.DEFAULT_TYPE):
    """Get the database connection from bot_data."""
    return context.bot_data["db_conn"]


def _safe_log(text: str | None, max_len: int = 200) -> str:
    """Sanitize user-supplied text for safe logging (strip control chars, truncate)."""
    if not text:
        return ""
    cleaned = "".join(ch if ch.isprintable() or ch == " " else "?" for ch in text)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned


async def _drop_buttons(query, user_id: int) -> None:
    """Strip the inline keyboard from the message that owns this callback query.

    Edits can fail (message too old, already edited, etc.) — that's not fatal,
    so we log at debug and move on.
    """
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not strip keyboard: %s", e, extra={"user_id": user_id})


def _format_word_tables(words: list[dict], show_ids: bool = True) -> str:
    """Format words grouped by POS as readable tables. HTML-escaped.

    ``show_ids=True`` (default) prints the ``[id]`` prefix used by /list (and
    referenced by /delete to disambiguate matches). /add post-save passes False
    because the user just typed the words and doesn't need internal IDs surfaced.
    """
    groups: dict[str, list[dict]] = {}
    for w in words:
        pos = w["part_of_speech"]
        groups.setdefault(pos, []).append(w)

    lines = []
    pos_labels = {
        "n": "Nouns",
        "v": "Verbs",
        "adj": "Adjectives",
        "adv": "Adverbs",
        "prep": "Prepositions",
    }

    def esc(s) -> str:
        return html.escape(str(s)) if s is not None else ""

    for pos in ["n", "v", "adj", "adv", "prep"]:
        if pos not in groups:
            continue
        lines.append(f"\n<b>{pos_labels.get(pos, pos)}:</b>")
        for w in groups[pos]:
            wid = w.get("id")
            id_prefix = f"[{wid}] " if (show_ids and wid is not None) else ""
            german = esc(w["german"])
            translation = esc(w["translation"])
            if pos == "n":
                article = esc(w.get("article")) or "?"
                plural = esc(w.get("plural")) or "—"
                lines.append(f"  {id_prefix}{article} {german} (pl: {plural}) — {translation}")
            elif pos == "v":
                partizip = esc(w.get("partizip_ii")) or "—"
                forms_str = ""
                forms = parse_irregular_forms(w.get("irregular_forms"))
                if forms:
                    form_parts = [f"{esc(k)}: {esc(v)}" for k, v in forms.items()]
                    forms_str = f" ({', '.join(form_parts)})"
                lines.append(f"  {id_prefix}{german} [{partizip}]{forms_str} — {translation}")
            else:
                lines.append(f"  {id_prefix}{german} — {translation}")

    return "\n".join(lines)


def _parse_quiz_args(args: list[str]) -> tuple[int | None, str | None]:
    """Parse ``/quiz`` and ``/learn`` args. Returns (size, tag); either may be None.

    Order-independent: the first purely-numeric arg is treated as size, the
    first non-numeric arg as tag (with optional leading #). Used by both
    /quiz and /learn to keep their CLI shape identical.
    """
    size: int | None = None
    tag: str | None = None
    for raw in args:
        candidate = raw.lstrip("#")
        if size is None and candidate.isdigit():
            size = int(candidate)
        elif tag is None:
            tag = candidate
    return size, tag
