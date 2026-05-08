"""Simple one-shot commands plus the global error handler."""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import LIST_MAX_WORDS, QUIZ_START_MESSAGE
from bot.database import (
    delete_word,
    find_words_by_german,
    get_tags,
    get_words,
)
from bot.logging_config import get_logger, log_user_action, log_user_error
from bot.stats import get_user_stats

from ._shared import CB_HELP, _format_word_tables, _get_conn, _safe_log

logger = get_logger(__name__)


# Help/start text — kept here because they reference each other and the
# ADD_FORMAT_MESSAGE constant from /add. The HTML escapes (e.g. &lt;id|all&gt;)
# are deliberate; without them Telegram rejects the message.
COMMANDS_HELP = (
    "<b>Commands:</b>\n"
    "/add [tag] — add new words (optionally with a tag)\n"
    "/list tag — list words filtered by tag\n"
    "/tags — show all your tags\n"
    "/delete word — delete a word by its German text\n"
    "/quiz [N] [tag] — start a quiz (N questions, default 7; words repeat if vocab is small)\n"
    "/learn [N] [tag] — learn new (or Blackout-flagged) words; graduates them into /quiz\n"
    "/stats — show learning statistics\n"
    "/remindme HH:MM [tz] — add a daily practice reminder (default Europe/Berlin)\n"
    "/reminders — list your reminders (Berlin/Moscow times)\n"
    "/remindoff &lt;id|all&gt; — remove a reminder\n"
    "/help — interactive help menu\n"
    "/cancel — abort an active quiz (partial progress is saved)"
)

START_MESSAGE = (
    "Welcome to Wortschatz — your German vocabulary trainer!\n\n"
    + COMMANDS_HELP
    + "\n\n"
    + QUIZ_START_MESSAGE
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_user_action(logger, update.effective_user.id, "/start")
    await update.message.reply_text(START_MESSAGE, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_user_action(logger, update.effective_user.id, "/help")
    keyboard = [
        [
            InlineKeyboardButton("Commands", callback_data=f"{CB_HELP}commands"),
            InlineKeyboardButton("How to add words", callback_data=f"{CB_HELP}add"),
            InlineKeyboardButton("How quizzes work", callback_data=f"{CB_HELP}quiz"),
        ]
    ]
    await update.message.reply_text(
        "What do you need help with?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Imported lazily to avoid a circular reference between simple.py and add.py
    # (add.py owns ADD_FORMAT_MESSAGE; simple.py owns help_callback that shows it).
    from .add import ADD_FORMAT_MESSAGE

    query = update.callback_query
    await query.answer()
    topic = query.data.removeprefix(CB_HELP)

    if topic == "commands":
        text = COMMANDS_HELP
    elif topic == "add":
        text = ADD_FORMAT_MESSAGE
    elif topic == "quiz":
        text = (
            "<b>How quizzes work:</b>\n\n"
            "Use <code>/quiz [N] [tag]</code> — both args optional.\n"
            "  <code>/quiz</code> — 7 mixed questions on most-due words\n"
            "  <code>/quiz 20</code> — 20 questions\n"
            "  <code>/quiz animals</code> — filter by tag\n"
            "  <code>/quiz 10 animals</code> — combine\n\n"
            "If your vocabulary is smaller than the requested size, words repeat "
            "with new quiz types each round.\n\n"
            "Question types (mixed within a session):\n"
            "- Translate: type the German word\n"
            "- Multiple choice: pick the translation\n"
            "- Article: pick der/die/das (nouns only)\n"
            "- Verb forms: type the asked form (irregular verbs only)\n\n" + QUIZ_START_MESSAGE
        )
    else:
        text = "Unknown topic."

    await query.edit_message_text(text, parse_mode="HTML")


async def tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/tags")
    conn = _get_conn(context)
    tags = await get_tags(conn, user_id)
    if not tags:
        await update.message.reply_text("You have no tags yet.")
        return
    await update.message.reply_text("Your tags:\n" + "\n".join(f"  #{t}" for t in tags))


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/list {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)

    if not context.args:
        await update.message.reply_text(
            "Please specify a tag: /list tag\nUse /tags to see your tags."
        )
        return

    tag = context.args[0].lstrip("#")
    words = await get_words(conn, user_id, tag=tag)
    if not words:
        await update.message.reply_text(f"No words found with tag #{tag}.")
        return

    total = len(words)
    truncated = total > LIST_MAX_WORDS
    words = words[:LIST_MAX_WORDS]
    safe_tag = html.escape(tag)
    text = f"Words with tag <b>#{safe_tag}</b> ({total} total):"
    text += _format_word_tables(words)
    if truncated:
        text += f"\n\n... and {total - LIST_MAX_WORDS} more."

    await update.message.reply_text(text, parse_mode="HTML")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/delete {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)

    # Clear any stale pending_delete from a previous call
    context.user_data.pop("pending_delete", None)

    if not context.args:
        await update.message.reply_text("Usage: /delete german_word")
        return

    german = " ".join(context.args)
    matches = await find_words_by_german(conn, user_id, german)

    if not matches:
        await update.message.reply_text(f"No word '{german}' found in your vocabulary.")
        return

    if len(matches) > 1:
        lines = [f"Multiple matches for '{german}':"]
        for w in matches:
            pos = w["part_of_speech"]
            lines.append(f"  [{w['id']}] {pos}: {w['german']} — {w['translation']}")
        lines.append("\nDelete all of them? Use /delete_confirm to confirm.")
        context.user_data["pending_delete"] = [w["id"] for w in matches]
        await update.message.reply_text("\n".join(lines))
        return

    word = matches[0]
    deleted = await delete_word(conn, user_id, word["id"])
    if deleted:
        await update.message.reply_text(f"Deleted: {word['german']} — {word['translation']}")
    else:
        await update.message.reply_text("Failed to delete word.")


async def delete_confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/delete_confirm")
    conn = _get_conn(context)

    pending = context.user_data.get("pending_delete")
    if not pending:
        await update.message.reply_text("Nothing to confirm.")
        return

    count = 0
    for word_id in pending:
        if await delete_word(conn, user_id, word_id):
            count += 1

    context.user_data.pop("pending_delete", None)
    await update.message.reply_text(f"Deleted {count} word(s).")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/stats")
    conn = _get_conn(context)
    text = await get_user_stats(conn, user_id)
    await update.message.reply_text(text, parse_mode="HTML")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update and update.effective_user else 0
    err = context.error
    log_user_error(
        logger,
        user_id,
        f"Unhandled error: {err!r}",
        exc_info=err if isinstance(err, BaseException) else True,
    )
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong, please try again later."
            )
        except Exception as e:
            logger.error("Failed to send error message to user: %s", e, extra={"user_id": user_id})
