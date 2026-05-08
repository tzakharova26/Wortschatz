"""/add conversation: collect word lines, preview, confirm or cancel via buttons."""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.database import (
    add_word,
    find_word_by_german_pos,
    merge_tag,
    update_word_tags,
)
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning

from ._shared import (
    ADD_CONFIRM,
    ADD_WORDS,
    CB_ADD,
    CB_LEARN_BATCH,
    _drop_buttons,
    _format_word_tables,
    _get_conn,
    _safe_log,
)
from .parsers import _parse_word_line

logger = get_logger(__name__)


ADD_FORMAT_MESSAGE = (
    "Send words, one per line. Fields can be separated by spaces or by | (pipe).\n\n"
    "<code>n article word plural translation</code>\n"
    "Example: <code>n die Katze Katzen cat</code>\n"
    "Or:      <code>n | die | Katze | Katzen | small cat</code>\n\n"
    "<code>v infinitive partizip_ii translation</code>  (regular)\n"
    "Example: <code>v machen hat gemacht to do</code>\n"
    "Or:      <code>v | machen | hat gemacht | to do something</code>\n\n"
    "<code>vi infinitive partizip_ii ich du er translation</code>  (irregular)\n"
    "Example: <code>vi fahren ist gefahren fahre faehrst faehrt to drive</code>\n"
    "Or:      <code>vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive</code>\n\n"
    "<code>adj word translation</code>\n"
    "Example: <code>adj schnell fast</code>\n\n"
    "<code>adv word translation</code>\n"
    "Example: <code>adv manchmal sometimes</code>\n\n"
    "<code>prep word translation</code>  (case info goes in translation)\n"
    "Example: <code>prep mit with (+dat)</code>\n\n"
    "After parsing, you'll see a preview with Confirm and Cancel buttons."
)


def _clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("parsed_words", "add_tag"):
        context.user_data.pop(k, None)


def _add_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"{CB_ADD}cancel")]])


def _add_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"{CB_ADD}confirm"),
                InlineKeyboardButton("Cancel", callback_data=f"{CB_ADD}cancel"),
            ]
        ]
    )


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    _clear_add_state(context)

    tag = ""
    if context.args:
        tag = context.args[0].lstrip("#")
    context.user_data["add_tag"] = tag
    log_user_action(logger, user_id, f"/add tag={_safe_log(tag) or 'none'}")

    safe_tag = html.escape(tag)
    header = f"Adding words with tag <b>#{safe_tag}</b>.\n\n" if tag else ""
    await update.message.reply_text(
        header + ADD_FORMAT_MESSAGE,
        parse_mode="HTML",
        reply_markup=_add_cancel_keyboard(),
    )
    return ADD_WORDS


async def add_words_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    parsed = []
    errors = []
    for line in text.strip().split("\n"):
        word_dict, error = _parse_word_line(line)
        if error:
            errors.append(error)
        elif word_dict:
            parsed.append(word_dict)

    if errors:
        error_text = "Errors found:\n" + "\n".join(f"  - {e}" for e in errors)
        if parsed:
            error_text += f"\n\n{len(parsed)} valid line(s) ready."
            error_text += (
                "\n\nFix errors and resend, /skip to preview valid lines only, " "or tap Cancel."
            )
        else:
            error_text += "\n\nFix errors and resend, or tap Cancel."
        await update.message.reply_text(
            error_text, parse_mode="HTML", reply_markup=_add_cancel_keyboard()
        )
        context.user_data["parsed_words"] = parsed
        return ADD_WORDS

    if not parsed:
        await update.message.reply_text(
            "No valid words found. Try again or tap Cancel.",
            reply_markup=_add_cancel_keyboard(),
        )
        return ADD_WORDS

    context.user_data["parsed_words"] = parsed
    return await _send_preview(update, parsed)


async def add_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show preview of the already-parsed valid lines (errors skipped)."""
    parsed = context.user_data.get("parsed_words", [])
    if not parsed:
        await update.message.reply_text("No valid words to preview. /cancel to abort.")
        return ADD_WORDS
    return await _send_preview(update, parsed)


async def _send_preview(update: Update, parsed: list[dict]) -> int:
    """Render the preview of parsed words and prompt the user to confirm via buttons."""
    preview = _format_word_tables(parsed)
    await update.message.reply_text(
        f"Preview ({len(parsed)} word(s)):{preview}\n\n"
        "Tap Confirm to save, Cancel to abort, or send more words to replace this batch.",
        parse_mode="HTML",
        reply_markup=_add_confirm_keyboard(),
    )
    return ADD_CONFIRM


async def add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the Confirm / Cancel inline buttons in the /add flow."""
    query = update.callback_query
    await query.answer()
    action = query.data.removeprefix(CB_ADD)
    user_id = update.effective_user.id

    if action == "cancel":
        log_user_action(logger, user_id, "/add cancelled via button")
        _clear_add_state(context)
        await _drop_buttons(query, user_id)
        await query.message.reply_text("Add cancelled.")
        return ConversationHandler.END

    if action == "confirm":
        log_user_action(logger, user_id, "/add confirmed via button")
        conn = _get_conn(context)
        tag = context.user_data.get("add_tag", "")
        parsed = context.user_data.get("parsed_words", [])
        await _drop_buttons(query, user_id)
        if not parsed:
            await query.message.reply_text("Nothing to save. Send /add to start over.")
            _clear_add_state(context)
            return ConversationHandler.END
        return await _save_words(update, context, parsed, conn, user_id, tag)

    log_user_warning(logger, user_id, f"Unknown /add callback action: {action!r}")
    return ADD_CONFIRM


async def _save_words(update, context, parsed, conn, user_id, tag) -> int:
    """Save parsed words. If a word with same (german, POS) already exists,
    merge the new tag into its existing tags instead of creating a duplicate row."""
    added = []  # newly inserted
    merged = []  # existing word, tag added
    unchanged = []  # existing word, tag already present (or no tag given)

    for w in parsed:
        try:
            existing = await find_word_by_german_pos(
                conn, user_id, w["german"], w["part_of_speech"]
            )
            if existing is not None:
                new_tags, changed = merge_tag(existing["tags"], tag)
                if changed:
                    await update_word_tags(conn, user_id, existing["id"], new_tags)
                    w["id"] = existing["id"]
                    w["tags"] = new_tags
                    merged.append(w)
                else:
                    w["id"] = existing["id"]
                    w["tags"] = existing["tags"]
                    unchanged.append(w)
                continue

            word_id = await add_word(
                conn,
                user_id,
                w["part_of_speech"],
                w["german"],
                w["translation"],
                article=w.get("article"),
                plural=w.get("plural"),
                partizip_ii=w.get("partizip_ii"),
                irregular_forms=w.get("irregular_forms"),
                tags=tag,
            )
            w["id"] = word_id
            added.append(w)
        except ValueError as e:
            log_user_warning(logger, user_id, f"Failed to add word: {_safe_log(str(e))}")
            await update.effective_message.reply_text(f"Error: {html.escape(str(e))}")
        except Exception as e:
            safe_german = _safe_log(str(w.get("german", "?")))
            log_user_error(logger, user_id, f"DB error adding word '{safe_german}': {e}")
            await update.effective_message.reply_text(
                f"Could not save '{html.escape(str(w.get('german', '?')))}'. "
                "Database error — others may still be saved."
            )

    parts: list[str] = []
    if added:
        parts.append(f"Added {len(added)} new word(s):{_format_word_tables(added)}")
    if merged:
        safe_tag = html.escape(tag)
        parts.append(
            f"Tag <b>#{safe_tag}</b> added to {len(merged)} existing word(s):"
            + _format_word_tables(merged)
        )
    if unchanged:
        names = ", ".join(html.escape(w["german"]) for w in unchanged)
        parts.append(f"Already existed (no change): {names}")

    markup = None
    if added:
        # Stash the freshly-added IDs so the "Start learning" button can scope to them.
        ids = [w["id"] for w in added]
        context.user_data["pending_learn_ids"] = ids
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Start learning ({len(ids)})",
                        callback_data=f"{CB_LEARN_BATCH}go",
                    )
                ]
            ]
        )

    if not parts:
        await update.effective_message.reply_text("No words were saved.")
    else:
        await update.effective_message.reply_text(
            "\n\n".join(parts), parse_mode="HTML", reply_markup=markup
        )

    _clear_add_state(context)
    return ConversationHandler.END


def get_add_conversation() -> ConversationHandler:
    add_cb_handler = CallbackQueryHandler(add_callback, pattern=f"^{CB_ADD}")
    return ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_WORDS: [
                CommandHandler("skip", add_skip),
                add_cb_handler,
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_words_received),
            ],
            ADD_CONFIRM: [
                add_cb_handler,
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_words_received),
            ],
        },
        fallbacks=[],
    )
