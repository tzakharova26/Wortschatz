"""/learn conversation: massed-drill flow for new and Blackout-flagged words.

Note the namespace import: ``from bot import learn as learn_core``. The core
``bot.learn`` module owns the session/step types; this submodule is the
Telegram handler layer for /learn. Keeping the import as a namespace (not
six aliased ``from bot.learn import X as LEARN_X_TYPE`` lines) is both
shorter and avoids the visual coupling.
"""

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

from bot import learn as learn_core
from bot.config import LEARN_MAX_SIZE, LEARN_MIN_SIZE, LEARN_START_MESSAGE
from bot.database import get_needs_learning_words, get_words_by_pos
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning

from ._shared import (
    CB_LEARN_ART,
    CB_LEARN_BATCH,
    CB_LEARN_MC,
    CB_LEARN_SHOW,
    LEARN_ANSWERING,
    _drop_buttons,
    _get_conn,
    _parse_quiz_args,
    _safe_log,
)

logger = get_logger(__name__)


def _clear_learn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("learn_session", None)


def _build_learn_step_markup(step) -> InlineKeyboardMarkup | None:
    """Inline keyboard for the current learn step. Typed/verb_form/plural steps return None."""
    if step.step_type == learn_core.SHOW:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Got it", callback_data=f"{CB_LEARN_SHOW}ok")]]
        )
    if step.step_type == learn_core.MC and step.options:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(o, callback_data=f"{CB_LEARN_MC}{o}")] for o in step.options]
        )
    if step.step_type == learn_core.ARTICLE and step.options:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(o, callback_data=f"{CB_LEARN_ART}{o}") for o in step.options]]
        )
    return None


async def _send_learn_step(reply_target, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the current step. reply_target must support .reply_text()."""
    session: learn_core.LearnSession = context.user_data["learn_session"]
    step = session.current_step
    if step is None:
        return

    markup = _build_learn_step_markup(step)
    idx = session.current_index + 1
    total = len(session.steps)
    retry_tag = " (retry)" if step.is_retry else ""
    if step.step_type == learn_core.SHOW:
        text = f"<b>Step {idx}/{total} — see card</b>{retry_tag}\n\n{step.prompt}"
    else:
        text = f"<b>Step {idx}/{total}</b>{retry_tag}\n{html.escape(step.prompt)}"
    await reply_target.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def _start_learn_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    words: list[dict],
    reply_target,
) -> int:
    """Shared session-bootstrap used by both /learn and the post-/add button."""
    if not words:
        await reply_target.reply_text(
            "Nothing to learn — every word has been seen at least once. Use /add to "
            "add new words, or /quiz to revise existing ones."
        )
        return ConversationHandler.END

    conn = _get_conn(context)
    all_user_words: list[dict] = []
    for pos in ("n", "v", "adj", "adv", "prep"):
        all_user_words.extend(await get_words_by_pos(conn, user_id, pos))

    session = learn_core.build_session(user_id, words, all_user_words)
    context.user_data["learn_session"] = session

    intro = LEARN_START_MESSAGE.format(n=len(words))
    await reply_target.reply_text(intro)
    await _send_learn_step(reply_target, context)
    return LEARN_ANSWERING


async def learn_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /learn [N] [tag]. Mirrors /quiz arg parsing."""
    user_id = update.effective_user.id
    _clear_learn_state(context)
    requested_size, tag = _parse_quiz_args(context.args or [])

    if requested_size is not None and requested_size <= 0:
        await update.message.reply_text("Learn size must be a positive number.")
        return ConversationHandler.END

    notice: str | None = None
    if requested_size is not None and requested_size > LEARN_MAX_SIZE:
        notice = f"(Capped to {LEARN_MAX_SIZE} words.)"
        requested_size = LEARN_MAX_SIZE
    elif requested_size is not None and requested_size < LEARN_MIN_SIZE:
        notice = f"(Bumped to minimum of {LEARN_MIN_SIZE} words.)"
        requested_size = LEARN_MIN_SIZE
    size = requested_size if requested_size is not None else LEARN_MAX_SIZE

    log_user_action(logger, user_id, f"/learn size={size} tag={_safe_log(tag) if tag else 'all'}")

    conn = _get_conn(context)
    words = await get_needs_learning_words(conn, user_id, limit=size, tag=tag)
    if notice:
        await update.message.reply_text(notice)
    return await _start_learn_session(update, context, user_id, words, update.message)


async def learn_batch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Post-/add 'Start learning' button. Scopes to the just-added word IDs
    stashed in user_data['pending_learn_ids']."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    word_ids = context.user_data.pop("pending_learn_ids", None) or []
    log_user_action(logger, user_id, f"/learn launched from /add (ids={word_ids})")

    await _drop_buttons(query, user_id)

    if not word_ids:
        await query.message.reply_text(
            "Those new words are no longer available — try /learn directly."
        )
        return ConversationHandler.END

    conn = _get_conn(context)
    # Restrict to ids that are still in the needs-learning pool.
    words = await get_needs_learning_words(conn, user_id, word_ids=word_ids)
    return await _start_learn_session(update, context, user_id, words, query.message)


async def learn_button_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles SHOW/MC/ARTICLE button taps."""
    query = update.callback_query
    await query.answer()

    session: learn_core.LearnSession | None = context.user_data.get("learn_session")
    if not session or session.is_finished:
        await query.message.reply_text("No active learning session. Use /learn to start one.")
        return ConversationHandler.END

    step = session.current_step
    data = query.data or ""

    if data.startswith(CB_LEARN_SHOW):
        # SHOW step: any tap acknowledges; always counts as passed. Strip the
        # button by editing the message's reply markup — don't re-send the card
        # text (echoing user-rendered HTML back through parse_mode="HTML" is
        # fragile and could amplify any HTML if _show_prompt ever changed).
        session.record_step(correct=True)
        await _drop_buttons(query, session.user_id)
    elif data.startswith(CB_LEARN_MC) or data.startswith(CB_LEARN_ART):
        prefix = CB_LEARN_MC if data.startswith(CB_LEARN_MC) else CB_LEARN_ART
        user_answer = data.removeprefix(prefix)
        correct = learn_core.check_answer(step, user_answer)
        session.record_step(correct=correct)
        feedback = _format_learn_feedback(step, correct)
        await query.edit_message_text(feedback, parse_mode="HTML")
    else:
        log_user_warning(logger, session.user_id, f"Unknown learn callback: {data!r}")
        return LEARN_ANSWERING

    if session.is_finished:
        return await _finish_learn(query.message, context)

    await _send_learn_step(query.message, context)
    return LEARN_ANSWERING


async def learn_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles TYPED, VERB_FORM, and PLURAL steps."""
    session: learn_core.LearnSession | None = context.user_data.get("learn_session")
    if not session or session.is_finished:
        await update.message.reply_text("No active learning session. Use /learn to start one.")
        return ConversationHandler.END

    step = session.current_step
    if step.step_type not in (learn_core.TYPED, learn_core.VERB_FORM, learn_core.PLURAL):
        # User typed during a button-only step. Just nudge them.
        await update.message.reply_text("Please use the buttons above.")
        return LEARN_ANSWERING

    user_answer = update.message.text.strip()
    correct = learn_core.check_answer(step, user_answer)
    session.record_step(correct=correct)
    feedback = _format_learn_feedback(step, correct)
    await update.message.reply_text(feedback, parse_mode="HTML")

    if session.is_finished:
        return await _finish_learn(update.message, context)

    await _send_learn_step(update.message, context)
    return LEARN_ANSWERING


def _format_learn_feedback(step, correct: bool) -> str:
    if step.step_type == learn_core.SHOW:
        return "Got it."
    safe_answer = html.escape(step.correct_answer or "")
    if correct:
        return f"Correct. ({safe_answer})"
    return f"Wrong. The answer is: <b>{safe_answer}</b>"


async def _finish_learn(reply_target, context: ContextTypes.DEFAULT_TYPE) -> int:
    session: learn_core.LearnSession = context.user_data["learn_session"]
    conn = _get_conn(context)
    try:
        graduated = await learn_core.apply_graduations(conn, session)
    except Exception as e:
        log_user_error(
            logger,
            session.user_id,
            f"Failed to apply graduations: {e}",
            exc_info=e,
        )
        graduated = -1

    summary = learn_core.format_summary(session)
    if graduated == -1:
        summary += "\n\n(Note: some graduations could not be saved due to a database error.)"
    await reply_target.reply_text(summary, parse_mode="HTML")
    log_user_action(
        logger,
        session.user_id,
        f"Learn finished: {len(session.graduated_words())}/"
        f"{len(session.required_per_word)} graduated",
    )
    _clear_learn_state(context)
    return ConversationHandler.END


async def learn_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Abort an active learning session. Any words that already fully passed are
    graduated before clearing state — same partial-progress idea as quiz_cancel."""
    user_id = update.effective_user.id
    session: learn_core.LearnSession | None = context.user_data.get("learn_session")
    log_user_action(logger, user_id, "Learn cancelled")

    if session and session.graduated_words():
        try:
            await learn_core.apply_graduations(_get_conn(context), session)
            summary = learn_core.format_summary(session)
            await update.message.reply_text(
                "Learning cancelled. Partial progress saved.\n\n" + summary,
                parse_mode="HTML",
            )
        except Exception as e:
            log_user_error(logger, user_id, f"Failed to save partial graduations: {e}", exc_info=e)
            await update.message.reply_text("Learning cancelled.")
    else:
        await update.message.reply_text("Learning cancelled.")

    _clear_learn_state(context)
    return ConversationHandler.END


def get_learn_conversation() -> ConversationHandler:
    learn_button_pattern = f"^({CB_LEARN_SHOW}|{CB_LEARN_MC}|{CB_LEARN_ART})"
    return ConversationHandler(
        entry_points=[
            CommandHandler("learn", learn_start),
            CallbackQueryHandler(learn_batch_callback, pattern=f"^{CB_LEARN_BATCH}"),
        ],
        states={
            LEARN_ANSWERING: [
                CallbackQueryHandler(learn_button_answer, pattern=learn_button_pattern),
                CommandHandler("cancel", learn_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, learn_text_answer),
            ],
        },
        fallbacks=[CommandHandler("cancel", learn_cancel)],
    )
