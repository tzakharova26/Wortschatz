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
from bot.config import LEARN_MAX_SIZE, LEARN_MIN_SIZE
from bot.database import get_needs_learning_words, get_words_by_pos
from bot.i18n import learn_start_message
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning
from bot.safety import LimitExceeded, ensure_db_size_allows_write

from ._shared import (
    CB_LEARN_ART,
    CB_LEARN_BATCH,
    CB_LEARN_MC,
    CB_LEARN_SHOW,
    LEARN_ANSWERING,
    _drop_buttons,
    _get_conn,
    _get_lang,
    _parse_quiz_args,
    _safe_log,
    pending_pop,
)

logger = get_logger(__name__)


def _clear_learn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("learn_session", None)
    context.user_data.pop("learn_message", None)
    context.user_data.pop("learn_message_text", None)
    context.user_data.pop("learn_feedback", None)


def _build_learn_step_markup(step, lang: str = "en") -> InlineKeyboardMarkup | None:
    """Inline keyboard for the current learn step. Typed/verb_form/plural steps return None."""
    if step.step_type == learn_core.SHOW:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Понятно" if lang == "ru" else "Got it",
                        callback_data=f"{CB_LEARN_SHOW}ok",
                    )
                ]
            ]
        )
    if step.step_type == learn_core.MC and step.options:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(o, callback_data=f"{CB_LEARN_MC}{idx}")]
                for idx, o in enumerate(step.options)
            ]
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

    markup = _build_learn_step_markup(step, session.lang)
    idx = session.current_index + 1
    # Retries get appended to ``steps`` only at end-of-main-run, but the user
    # should see the counter grow as soon as a wrong answer queues a retry.
    total = len(session.steps) + len(session.retry_queue)
    retry_tag = f" (retry {step.attempt - 1}/2)" if step.attempt > 1 else ""
    if session.lang == "ru":
        retry_tag = f" (повтор {step.attempt - 1}/2)" if step.attempt > 1 else ""
    if step.step_type == learn_core.SHOW:
        label = "Шаг" if session.lang == "ru" else "Step"
        see_card = "карточка" if session.lang == "ru" else "see card"
        text = f"<b>{label} {idx}/{total} — {see_card}</b>{retry_tag}\n\n{step.prompt}"
    else:
        label = "Шаг" if session.lang == "ru" else "Step"
        text = f"<b>{label} {idx}/{total}</b>{retry_tag}\n{html.escape(step.prompt)}"

    feedback = context.user_data.pop("learn_feedback", None)
    if feedback:
        text = feedback + "\n\n" + text
    await _edit_or_reply_session_message(
        context,
        "learn_message",
        reply_target,
        text,
        reply_markup=markup,
        force_new=True,
    )


async def _edit_or_reply_session_message(
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
    reply_target,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    force_new: bool = False,
) -> None:
    """Prefer editing the active bot message; fall back to sending a new one."""
    message = context.user_data.get(key)
    editable = message if hasattr(message, "edit_text") else None
    if editable is not None and not force_new:
        try:
            await editable.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            context.user_data[f"{key}_text"] = text
            return
        except Exception:
            log_user_warning(logger, 0, f"Failed to edit {key}; sending a new message")
    elif editable is not None and force_new:
        await _clear_previous_learn_buttons(context, key, editable)

    sent = await reply_target.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    if sent is not None:
        context.user_data[key] = sent
    context.user_data[f"{key}_text"] = text


async def _clear_previous_learn_buttons(
    context: ContextTypes.DEFAULT_TYPE,
    key: str,
    editable,
) -> None:
    """Before opening a new step message, remove buttons from the previous one."""
    previous_text = context.user_data.get(f"{key}_text")
    if not previous_text:
        return
    try:
        await editable.edit_text(previous_text, parse_mode="HTML")
    except Exception:
        log_user_warning(logger, 0, f"Failed to clear buttons on old {key}")


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
            (
                "Сейчас нечего учить — все слова уже хотя бы раз проходили /learn. "
                "Добавь новые через /add или повторяй старые через /quiz."
            )
            if await _get_lang(context, user_id) == "ru"
            else "Nothing to learn — every word has been seen at least once. Use /add to "
            "add new words, or /quiz to revise existing ones."
        )
        return ConversationHandler.END

    conn = _get_conn(context)
    all_user_words: list[dict] = []
    for pos in ("n", "v", "adj", "adv", "prep", "phrase"):
        all_user_words.extend(await get_words_by_pos(conn, user_id, pos))

    lang = await _get_lang(context, user_id)
    session = learn_core.build_session(user_id, words, all_user_words, lang=lang)
    context.user_data["learn_session"] = session

    intro = learn_start_message(len(words), lang)
    await reply_target.reply_text(intro)
    await _send_learn_step(reply_target, context)
    return LEARN_ANSWERING


async def learn_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /learn [N] [tag]. Mirrors /quiz arg parsing."""
    user_id = update.effective_user.id
    lang = await _get_lang(context, user_id)
    _clear_learn_state(context)
    requested_size, tag = _parse_quiz_args(context.args or [])

    if requested_size is not None and requested_size <= 0:
        await update.message.reply_text(
            "Размер /learn должен быть положительным числом."
            if lang == "ru"
            else "Learn size must be a positive number."
        )
        return ConversationHandler.END

    notice: str | None = None
    if requested_size is not None and requested_size > LEARN_MAX_SIZE:
        notice = (
            f"(Ограничено до {LEARN_MAX_SIZE} слов.)"
            if lang == "ru"
            else f"(Capped to {LEARN_MAX_SIZE} words.)"
        )
        requested_size = LEARN_MAX_SIZE
    elif requested_size is not None and requested_size < LEARN_MIN_SIZE:
        notice = (
            f"(Поднято до минимума: {LEARN_MIN_SIZE} слов.)"
            if lang == "ru"
            else f"(Bumped to minimum of {LEARN_MIN_SIZE} words.)"
        )
        requested_size = LEARN_MIN_SIZE
    size = requested_size if requested_size is not None else LEARN_MAX_SIZE

    log_user_action(logger, user_id, f"/learn size={size} tag={_safe_log(tag) if tag else 'all'}")

    conn = _get_conn(context)
    try:
        await ensure_db_size_allows_write(conn, user_id)
    except LimitExceeded as e:
        log_user_warning(logger, user_id, e.log_message)
        await update.message.reply_text(e.user_message)
        return ConversationHandler.END

    old_limit = size // 2
    blackout_words = await get_needs_learning_words(
        conn,
        user_id,
        limit=old_limit,
        tag=tag,
        learning_status="blackout",
    )
    new_words = await get_needs_learning_words(
        conn,
        user_id,
        limit=size - len(blackout_words),
        tag=tag,
        learning_status="new",
    )
    words = blackout_words + new_words
    if notice:
        await update.message.reply_text(notice)
    return await _start_learn_session(update, context, user_id, words, update.message)


async def learn_batch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Post-/add 'Start learning' button. Scopes to the just-added word IDs
    stashed in user_data['pending_learn_ids']."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    word_ids = pending_pop(context, "pending_learn_ids") or []
    log_user_action(logger, user_id, f"/learn launched from /add (ids={word_ids})")

    await _drop_buttons(query, user_id)

    if not word_ids:
        await query.message.reply_text(
            (
                "Эти новые слова уже недоступны — попробуй /learn напрямую."
                if await _get_lang(context, user_id) == "ru"
                else "Those new words are no longer available — try /learn directly."
            )
        )
        return ConversationHandler.END

    conn = _get_conn(context)
    try:
        await ensure_db_size_allows_write(conn, user_id)
    except LimitExceeded as e:
        log_user_warning(logger, user_id, e.log_message)
        await query.message.reply_text(e.user_message)
        return ConversationHandler.END

    # Restrict to ids that are still in the needs-learning pool.
    words = await get_needs_learning_words(conn, user_id, word_ids=word_ids)
    return await _start_learn_session(update, context, user_id, words, query.message)


async def learn_button_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles SHOW/MC/ARTICLE button taps."""
    query = update.callback_query
    await query.answer()

    session: learn_core.LearnSession | None = context.user_data.get("learn_session")
    if not session or session.is_finished:
        lang = await _get_lang(context, update.effective_user.id)
        await query.message.reply_text(
            "Нет активной сессии обучения. Используй /learn, чтобы начать."
            if lang == "ru"
            else "No active learning session. Use /learn to start one."
        )
        return ConversationHandler.END

    step = session.current_step
    data = query.data or ""

    if data.startswith(CB_LEARN_SHOW):
        # SHOW step: any tap acknowledges; always counts as passed. Strip the
        # button by editing the message's reply markup — don't re-send the card
        # text (echoing user-rendered HTML back through parse_mode="HTML" is
        # fragile and could amplify any HTML if _show_prompt ever changed).
        session.record_step(correct=True)
    elif data.startswith(CB_LEARN_MC) or data.startswith(CB_LEARN_ART):
        prefix = CB_LEARN_MC if data.startswith(CB_LEARN_MC) else CB_LEARN_ART
        raw_answer = data.removeprefix(prefix)
        if prefix == CB_LEARN_MC and raw_answer.isdigit() and step.options:
            idx = int(raw_answer)
            if idx >= len(step.options):
                log_user_warning(logger, session.user_id, f"Invalid learn MC index: {raw_answer}")
                return LEARN_ANSWERING
            user_answer = step.options[idx]
        else:
            # Legacy callback shape from messages sent before callback data was shortened.
            user_answer = raw_answer
        correct = learn_core.check_answer(step, user_answer)
        session.record_step(correct=correct)
        context.user_data["learn_feedback"] = _format_learn_feedback(step, correct, session.lang)
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
        lang = await _get_lang(context, update.effective_user.id)
        await update.message.reply_text(
            "Нет активной сессии обучения. Используй /learn, чтобы начать."
            if lang == "ru"
            else "No active learning session. Use /learn to start one."
        )
        return ConversationHandler.END

    step = session.current_step
    if step.step_type not in (
        learn_core.TYPED,
        learn_core.VERB_FORM,
        learn_core.PLURAL,
        learn_core.ADJECTIVE_EXAMPLE,
    ):
        # User typed during a button-only step. Resend the current prompt with
        # buttons, because the original Telegram message may have scrolled away
        # or lost its inline keyboard after an edit/restart.
        await update.message.reply_text(
            "Пришлю кнопки еще раз." if session.lang == "ru" else "I’ll resend the buttons."
        )
        await _send_learn_step(update.message, context)
        return LEARN_ANSWERING

    user_answer = update.message.text.strip()
    correct = learn_core.check_answer(step, user_answer)
    session.record_step(correct=correct)
    context.user_data["learn_feedback"] = _format_learn_feedback(step, correct, session.lang)

    if session.is_finished:
        return await _finish_learn(update.message, context)

    await _send_learn_step(update.message, context)
    return LEARN_ANSWERING


def _format_learn_feedback(step, correct: bool, lang: str = "en") -> str:
    card_label = "Предыдущее слово" if lang == "ru" else "Previous word"
    card = learn_core.format_word_card(step.word)
    if correct:
        return f"<b>{card_label}</b>\n{card}"
    safe_answer = html.escape(step.correct_answer or "")
    if lang == "ru":
        return (
            f"<b>Повторим это позже.</b>\nОтвет: <b>{safe_answer}</b>\n\n"
            f"<b>{card_label}</b>\n{card}"
        )
    return (
        f"<b>Try this one again later.</b>\nAnswer: <b>{safe_answer}</b>\n\n"
        f"<b>{card_label}</b>\n{card}"
    )


async def _finish_learn(reply_target, context: ContextTypes.DEFAULT_TYPE) -> int:
    session: learn_core.LearnSession = context.user_data["learn_session"]
    conn = _get_conn(context)
    try:
        await ensure_db_size_allows_write(conn, session.user_id)
        graduated = await learn_core.apply_graduations(conn, session)
        limit_message = None
    except LimitExceeded as e:
        log_user_warning(logger, session.user_id, e.log_message)
        graduated = -1
        limit_message = e.user_message
    except Exception as e:
        log_user_error(
            logger,
            session.user_id,
            f"Failed to apply graduations: {e}",
            exc_info=e,
        )
        graduated = -1
        limit_message = None

    summary = learn_core.format_summary(session)
    feedback = context.user_data.pop("learn_feedback", None)
    if feedback:
        summary = feedback + "\n\n" + summary
    if graduated == -1 and limit_message:
        summary += f"\n\n{html.escape(limit_message)}"
    elif graduated == -1:
        summary += (
            "\n\n(Примечание: часть прогресса не удалось сохранить из-за ошибки базы данных.)"
            if session.lang == "ru"
            else "\n\n(Note: some graduations could not be saved due to a database error.)"
        )
    await _edit_or_reply_session_message(
        context,
        "learn_message",
        reply_target,
        summary,
    )
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
    lang = await _get_lang(context, user_id)
    session: learn_core.LearnSession | None = context.user_data.get("learn_session")
    log_user_action(logger, user_id, "Learn cancelled")

    if session and session.graduated_words():
        conn = _get_conn(context)
        try:
            await ensure_db_size_allows_write(conn, user_id)
            await learn_core.apply_graduations(conn, session)
            summary = learn_core.format_summary(session)
            await update.message.reply_text(
                (
                    "Обучение отменено. Частичный прогресс сохранен.\n\n"
                    if lang == "ru"
                    else "Learning cancelled. Partial progress saved.\n\n"
                )
                + summary,
                parse_mode="HTML",
            )
        except LimitExceeded as e:
            log_user_warning(logger, user_id, e.log_message)
            await update.message.reply_text(
                ("Обучение отменено.\n\n" if lang == "ru" else "Learning cancelled.\n\n")
                + e.user_message
            )
        except Exception as e:
            log_user_error(logger, user_id, f"Failed to save partial graduations: {e}", exc_info=e)
            await update.message.reply_text(
                "Обучение отменено." if lang == "ru" else "Learning cancelled."
            )
    else:
        await update.message.reply_text(
            "Обучение отменено." if lang == "ru" else "Learning cancelled."
        )

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
