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
from bot.database import (
    get_due_words,
    get_learning_overview,
    get_needs_learning_words,
    get_words_by_pos,
    parse_irregular_forms,
)
from bot.logging_config import get_logger, log_user_action, log_user_warning
from bot.progress import format_quiz_intro
from bot.quiz import (
    apply_results,
    build_quiz_session,
    check_answer,
    format_summary,
    german_with_article,
)

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

QUIZ_SELECTION_POOL_MULTIPLIER = 4


def _clear_quiz_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("quiz_session", "quiz_all_words", "last_answer_correct", "quiz_message"):
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

    await _edit_or_reply_session_message(
        context,
        "quiz_message",
        reply_target,
        text,
        reply_markup=markup,
    )


async def _edit_or_reply_session_message(
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
    reply_target,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Prefer editing the active bot message; fall back to sending a new one."""
    message = context.user_data.get(key)
    editable = message if hasattr(message, "edit_text") else None
    if editable is not None:
        try:
            await editable.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return
        except Exception:
            log_user_warning(logger, 0, f"Failed to edit {key}; sending a new message")

    sent = await reply_target.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    if sent is not None:
        context.user_data[key] = sent


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

    # Pull a wider pool than the final session size. If we ask the DB for only
    # `size` rows, the same oldest-due words can dominate every default quiz
    # and recently graduated /learn words may not appear for a long time.
    pool_limit = min(QUIZ_MAX_SIZE, max(size * QUIZ_SELECTION_POOL_MULTIPLIER, size))
    due_words = await get_due_words(conn, user_id, limit=pool_limit, tag=tag)
    if not due_words:
        # Distinguish "user has no words yet" from "user has words but none are
        # graduated yet" — the second case should point at /learn, not /add.
        unlearned = await get_needs_learning_words(conn, user_id, limit=1, tag=tag)
        overview = await get_learning_overview(conn, user_id, tag=tag)
        msg = "No words are due for /quiz right now."
        if tag:
            msg += f" (tag: #{tag})"
        if unlearned:
            msg += f" {overview['needs_learning']} word(s) are waiting in /learn."
        elif overview["review_words"]:
            msg += " Your review words are scheduled for later by SM-2."
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

    overview = await get_learning_overview(conn, user_id, tag=tag)
    intro = format_quiz_intro(overview, tag=tag) + "\n\n" + QUIZ_START_MESSAGE
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


def _format_word_card(question) -> str:
    """Compact post-answer card with translation and relevant stored forms."""
    word = question.word
    lines = [
        f"<b>{html.escape(german_with_article(word))}</b>",
        f"= {html.escape(word['translation'])}",
    ]
    if word.get("part_of_speech") == "n":
        plural = word.get("plural")
        if plural and plural.strip():
            lines.append(f"plural: {html.escape(plural)}")
    elif word.get("part_of_speech") == "v":
        partizip = word.get("partizip_ii")
        if partizip and partizip.strip():
            lines.append(f"Partizip II: {html.escape(partizip)}")
        forms = parse_irregular_forms(word.get("irregular_forms"))
        if forms:
            forms_text = ", ".join(
                f"{html.escape(k)}: {html.escape(v)}" for k, v in forms.items() if v
            )
            if forms_text:
                lines.append(f"forms: {forms_text}")

    if question.quiz_type == "verb_forms" and question.verb_form_key:
        lines.append(
            f"asked: {html.escape(question.verb_form_key)} → "
            f"{html.escape(question.correct_answer)}"
        )
    elif question.quiz_type == "partizip":
        lines.append(f"asked: Partizip II → {html.escape(question.correct_answer)}")
    elif question.quiz_type == "plural":
        lines.append(f"asked: plural → {html.escape(question.correct_answer)}")
    return "\n".join(lines)


def _format_answer_response(question, correct: bool) -> str:
    """Build the post-answer card with HTML-escaped correct answer."""
    card = _format_word_card(question)
    if correct:
        return card + "\n\nHow did it feel?"
    safe_answer = html.escape(question.correct_answer or "")
    return f"<b>Not quite.</b>\nAnswer: <b>{safe_answer}</b>\n\n{card}\n\nHow did it feel?"


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
    await _edit_or_reply_session_message(
        context,
        "quiz_message",
        update.message,
        text,
        reply_markup=_rating_keyboard(correct),
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
    context.user_data["quiz_message"] = query.message
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
    else:
        try:
            quality = int(rate_data)
        except ValueError:
            log_user_warning(logger, session.user_id, f"Invalid rating data: {rate_data!r}")
            await query.edit_message_text("Invalid rating.")
            return QUIZ_RATING
        session.record_result(quality, correct)

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
    await _edit_or_reply_session_message(context, "quiz_message", query.message, summary)

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
