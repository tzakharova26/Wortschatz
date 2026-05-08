"""/quiz conversation: revision flow over due, already-graduated words."""

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

from bot.config import (
    QUALITY_BLACKOUT,
    QUALITY_EASY,
    QUALITY_GOOD,
    QUALITY_WRONG,
    QUIZ_MAX_SIZE,
    QUIZ_SESSION_SIZE,
    QUIZ_START_MESSAGE,
)
from bot.database import get_due_words, get_needs_learning_words, get_words_by_pos
from bot.logging_config import get_logger, log_user_action, log_user_warning
from bot.quiz import apply_results, build_quiz_session, check_answer, format_summary

from ._shared import (
    CB_ART,
    CB_MC,
    CB_RATE,
    QUIZ_ANSWERING,
    QUIZ_RATING,
    _get_conn,
    _parse_quiz_args,
    _safe_log,
)

logger = get_logger(__name__)


def _clear_quiz_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("quiz_session", "quiz_all_words", "last_answer_correct"):
        context.user_data.pop(k, None)


def _rating_keyboard(correct: bool) -> InlineKeyboardMarkup:
    """Return rating buttons: 2 relevant + misspell."""
    if correct:
        buttons = [
            InlineKeyboardButton("Good", callback_data=f"{CB_RATE}{QUALITY_GOOD}"),
            InlineKeyboardButton("Easy", callback_data=f"{CB_RATE}{QUALITY_EASY}"),
            InlineKeyboardButton("Misspell", callback_data=f"{CB_RATE}misspell"),
        ]
    else:
        buttons = [
            InlineKeyboardButton("Blackout", callback_data=f"{CB_RATE}{QUALITY_BLACKOUT}"),
            InlineKeyboardButton("Wrong", callback_data=f"{CB_RATE}{QUALITY_WRONG}"),
            InlineKeyboardButton("Misspell", callback_data=f"{CB_RATE}misspell"),
        ]
    return InlineKeyboardMarkup([buttons])


def _build_question_markup(q) -> InlineKeyboardMarkup | None:
    """Build the inline keyboard for a question, or None for typed answers."""
    if q.quiz_type == "multiple_choice" and q.options:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(opt, callback_data=f"{CB_MC}{opt}")] for opt in q.options]
        )
    if q.quiz_type == "article" and q.options:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(opt, callback_data=f"{CB_ART}{opt}") for opt in q.options]]
        )
    return None


async def _send_question(reply_target, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the current quiz question. reply_target must have .reply_text()."""
    session = context.user_data["quiz_session"]
    q = session.current_question
    if q is None:
        return

    markup = _build_question_markup(q)
    idx = session.current_index + 1
    total = len(session.questions)
    text = f"<b>Question {idx}/{total}</b>\n{html.escape(q.prompt)}"

    await reply_target.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    conn = _get_conn(context)
    _clear_quiz_state(context)

    requested_size, tag = _parse_quiz_args(context.args or [])

    if requested_size is not None and requested_size <= 0:
        await update.message.reply_text("Quiz size must be a positive number.")
        return ConversationHandler.END

    capped = False
    if requested_size is not None and requested_size > QUIZ_MAX_SIZE:
        requested_size = QUIZ_MAX_SIZE
        capped = True

    size = requested_size if requested_size is not None else QUIZ_SESSION_SIZE
    log_user_action(logger, user_id, f"/quiz size={size} tag={_safe_log(tag) if tag else 'all'}")

    # Fetch up to `size` most-due words; if user has fewer, build_quiz_session cycles.
    due_words = await get_due_words(conn, user_id, limit=size, tag=tag)
    if not due_words:
        # Distinguish "user has no words yet" from "user has words but none are
        # graduated yet" — the second case should point at /learn, not /add.
        unlearned = await get_needs_learning_words(conn, user_id, limit=1, tag=tag)
        msg = "No words to quiz on."
        if tag:
            msg += f" (tag: #{tag})"
        if unlearned:
            msg += " You have words that haven't graduated yet — use /learn first."
        else:
            msg += " Add some words first with /add."
        await update.message.reply_text(msg)
        return ConversationHandler.END

    # Collect all user words for multiple choice options
    all_user_words = []
    for pos in ("n", "v", "adj", "adv", "prep"):
        all_user_words.extend(await get_words_by_pos(conn, user_id, pos))

    session = build_quiz_session(user_id, due_words, all_user_words, size=size)
    context.user_data["quiz_session"] = session
    context.user_data["quiz_all_words"] = all_user_words

    intro = QUIZ_START_MESSAGE
    if capped:
        intro = f"(Capped to {QUIZ_MAX_SIZE} questions.)\n\n" + intro
    if len(due_words) < size:
        intro += (
            f"\nYou have only {len(due_words)} word(s) — they will repeat to fill "
            f"{size} questions."
        )
    await update.message.reply_text(intro, parse_mode="HTML")
    await _send_question(update.message, context)
    return QUIZ_ANSWERING


def _format_answer_response(question, correct: bool) -> str:
    """Build the 'Correct!/Wrong' message with HTML-escaped correct answer."""
    safe_answer = html.escape(question.correct_answer or "")
    if correct:
        return f"Correct! The answer is: <b>{safe_answer}</b>"
    return f"Wrong. The correct answer is: <b>{safe_answer}</b>"


async def quiz_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle typed answer (translate, verb_forms, plural)."""
    session = context.user_data.get("quiz_session")
    if not session or session.is_finished:
        await update.message.reply_text("No active quiz. Use /quiz to start one.")
        return ConversationHandler.END

    q = session.current_question
    user_answer = update.message.text.strip()
    correct = check_answer(q, user_answer)
    context.user_data["last_answer_correct"] = correct

    text = _format_answer_response(q, correct)
    await update.message.reply_text(
        text,
        reply_markup=_rating_keyboard(correct),
        parse_mode="HTML",
    )
    return QUIZ_RATING


async def quiz_button_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button answer (multiple_choice, article)."""
    query = update.callback_query
    await query.answer()

    session = context.user_data.get("quiz_session")
    if not session or session.is_finished:
        await query.message.reply_text("No active quiz. Use /quiz to start one.")
        return ConversationHandler.END

    q = session.current_question
    if query.data.startswith(CB_MC):
        user_answer = query.data.removeprefix(CB_MC)
    elif query.data.startswith(CB_ART):
        user_answer = query.data.removeprefix(CB_ART)
    else:
        return QUIZ_ANSWERING

    correct = check_answer(q, user_answer)
    context.user_data["last_answer_correct"] = correct

    text = _format_answer_response(q, correct)

    await query.edit_message_text(
        text,
        reply_markup=_rating_keyboard(correct),
        parse_mode="HTML",
    )
    return QUIZ_RATING


async def quiz_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle rating button press."""
    query = update.callback_query
    await query.answer()

    session = context.user_data.get("quiz_session")
    if not session or session.is_finished:
        await query.message.reply_text("No active quiz. Use /quiz to start one.")
        return ConversationHandler.END

    rate_data = query.data.removeprefix(CB_RATE)
    correct = context.user_data.get("last_answer_correct", False)

    if rate_data == "misspell":
        q = session.current_question
        all_words = context.user_data.get("quiz_all_words", [])
        session.add_misspell_question(q.word, all_words)
        session.record_misspell()
        await query.edit_message_text("Marked as misspell. Word will repeat later.")
    else:
        try:
            quality = int(rate_data)
        except ValueError:
            log_user_warning(logger, session.user_id, f"Invalid rating data: {rate_data!r}")
            await query.edit_message_text("Invalid rating.")
            return QUIZ_RATING
        session.record_result(quality, correct)
        await query.edit_message_text("Noted.")

    if session.is_finished:
        return await _finish_quiz(query, context)

    await _send_question(query.message, context)
    return QUIZ_ANSWERING


async def _finish_quiz(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish quiz: show summary, update SM-2 and history."""
    session = context.user_data["quiz_session"]
    failures = await apply_results(_get_conn(context), session)

    summary = format_summary(session)
    if failures:
        summary += f"\n\n(Note: {failures} result(s) could not be saved due to a database error.)"
    await query.message.reply_text(summary, parse_mode="HTML")

    _clear_quiz_state(context)
    user_id = session.user_id
    log_user_action(logger, user_id, f"Quiz finished: {session.score[0]}/{session.score[1]}")
    return ConversationHandler.END


async def quiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Abort an active quiz. Any answered+rated questions are persisted to SM-2
    and quiz_history before the session is cleared, so partial progress shows up
    in /stats."""
    user_id = update.effective_user.id
    session = context.user_data.get("quiz_session")
    rated = sum(1 for r in (session.results if session else []) if r is not None)
    log_user_action(logger, user_id, f"Quiz cancelled (rated={rated})")

    if session and rated > 0:
        failures = await apply_results(_get_conn(context), session)
        summary = format_summary(session)
        msg = "Quiz cancelled. Partial progress saved.\n\n" + summary
        if failures:
            msg += f"\n\n(Note: {failures} result(s) could not be saved due to a database error.)"
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text("Quiz cancelled.")

    _clear_quiz_state(context)
    return ConversationHandler.END


def get_quiz_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("quiz", quiz_start)],
        states={
            QUIZ_ANSWERING: [
                CallbackQueryHandler(quiz_button_answer, pattern=f"^({CB_MC}|{CB_ART})"),
                CommandHandler("cancel", quiz_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_text_answer),
            ],
            QUIZ_RATING: [
                CallbackQueryHandler(quiz_rating, pattern=f"^{CB_RATE}"),
                CommandHandler("cancel", quiz_cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", quiz_cancel)],
    )
