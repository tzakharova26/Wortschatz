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
    LIST_MAX_WORDS,
    QUALITY_BLACKOUT,
    QUALITY_EASY,
    QUALITY_GOOD,
    QUALITY_WRONG,
    QUIZ_SESSION_SIZE,
    QUIZ_START_MESSAGE,
)
from bot.database import (
    add_word,
    delete_word,
    find_words_by_german,
    get_due_words,
    get_tags,
    get_words,
    get_words_by_pos,
    parse_irregular_forms,
)
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning
from bot.quiz import (
    apply_results,
    build_quiz_session,
    check_answer,
    format_summary,
)
from bot.stats import get_user_stats
from bot.umlaut import convert_umlauts

logger = get_logger(__name__)

# ConversationHandler states
ADD_WORDS, QUIZ_ANSWERING, QUIZ_RATING = range(3)

# Callback data prefixes
CB_HELP = "help:"
CB_MC = "mc:"
CB_ART = "art:"
CB_RATE = "rate:"

ADD_FORMAT_MESSAGE = (
    "Send words, one per line. Formats:\n\n"
    "<code>n article word plural translation</code>\n"
    "Example: <code>n die Katze Katzen cat</code>\n\n"
    "<code>v infinitive partizip_ii translation</code>  (regular)\n"
    "Example: <code>v machen hat gemacht to do</code>\n\n"
    "<code>vi infinitive partizip_ii ich du er translation</code>  (irregular)\n"
    "Example: <code>vi fahren ist gefahren fahre faehrst faehrt to drive</code>\n\n"
    "<code>adj word translation</code>\n"
    "Example: <code>adj schnell fast</code>\n\n"
    "<code>adv word translation</code>\n"
    "Example: <code>adv manchmal sometimes</code>\n\n"
    "Send /cancel to abort."
)

COMMANDS_HELP = (
    "<b>Commands:</b>\n"
    "/add [tag] — add new words (optionally with a tag)\n"
    "/list tag — list words filtered by tag\n"
    "/tags — show all your tags\n"
    "/delete word — delete a word by its German text\n"
    "/quiz [tag] — start a 7-question quiz\n"
    "/stats — show learning statistics\n"
    "/help — interactive help menu\n"
    "/cancel — cancel current operation"
)

START_MESSAGE = (
    "Welcome to Wortschatz — your German vocabulary trainer!\n\n"
    + COMMANDS_HELP
    + "\n\n"
    + QUIZ_START_MESSAGE
)


# --- Helpers ---


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


def _clear_quiz_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("quiz_session", "quiz_all_words", "last_answer_correct"):
        context.user_data.pop(k, None)


def _clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("parsed_words", "add_tag"):
        context.user_data.pop(k, None)


def _format_word_tables(words: list[dict]) -> str:
    """Format words grouped by POS as readable tables."""
    groups: dict[str, list[dict]] = {}
    for w in words:
        pos = w["part_of_speech"]
        groups.setdefault(pos, []).append(w)

    lines = []
    pos_labels = {"n": "Nouns", "v": "Verbs", "adj": "Adjectives", "adv": "Adverbs"}

    def esc(s) -> str:
        return html.escape(str(s)) if s is not None else ""

    for pos in ["n", "v", "adj", "adv"]:
        if pos not in groups:
            continue
        lines.append(f"\n<b>{pos_labels.get(pos, pos)}:</b>")
        for w in groups[pos]:
            wid = w["id"]
            german = esc(w["german"])
            translation = esc(w["translation"])
            if pos == "n":
                article = esc(w.get("article")) or "?"
                plural = esc(w.get("plural")) or "—"
                lines.append(f"  [{wid}] {article} {german} (pl: {plural}) — {translation}")
            elif pos == "v":
                partizip = esc(w.get("partizip_ii")) or "—"
                forms_str = ""
                forms = parse_irregular_forms(w.get("irregular_forms"))
                if forms:
                    form_parts = [f"{esc(k)}: {esc(v)}" for k, v in forms.items()]
                    forms_str = f" ({', '.join(form_parts)})"
                lines.append(f"  [{wid}] {german} [{partizip}]{forms_str} — {translation}")
            else:
                lines.append(f"  [{wid}] {german} — {translation}")

    return "\n".join(lines)


def _parse_noun_line(parts: list[str], safe_line: str) -> tuple[dict | None, str | None]:
    if len(parts) < 5:
        return None, f"Noun needs: n article word plural translation: <code>{safe_line}</code>"
    return {
        "part_of_speech": "n",
        "german": convert_umlauts(parts[2]),
        "article": convert_umlauts(parts[1]),
        "plural": convert_umlauts(parts[3]),
        "partizip_ii": None,
        "irregular_forms": None,
        "translation": " ".join(parts[4:]),
    }, None


def _parse_verb_line(
    parts: list[str], is_irregular: bool, safe_line: str
) -> tuple[dict | None, str | None]:
    label = "vi" if is_irregular else "v"
    min_required = 7 if is_irregular else 4
    if len(parts) < min_required:
        if is_irregular:
            return None, (
                "vi needs: vi infinitive partizip_ii ich du er translation: "
                f"<code>{safe_line}</code>"
            )
        return None, f"v needs: v infinitive partizip_ii translation: <code>{safe_line}</code>"

    # partizip_ii is "ist X" / "hat X" (2 tokens) or a single token
    if parts[2] in ("ist", "hat"):
        if len(parts) < min_required + 1:
            return None, f"{label} with ist/hat needs more fields: <code>{safe_line}</code>"
        partizip_ii = f"{parts[2]} {convert_umlauts(parts[3])}"
        remaining = parts[4:]
    else:
        partizip_ii = convert_umlauts(parts[2])
        remaining = parts[3:]

    if is_irregular:
        if len(remaining) < 4:
            return None, f"vi needs ich, du, er, translation: <code>{safe_line}</code>"
        irregular_forms = {
            "ich": convert_umlauts(remaining[0]),
            "du": convert_umlauts(remaining[1]),
            "er": convert_umlauts(remaining[2]),
        }
        translation = " ".join(remaining[3:])
    else:
        if not remaining:
            return None, f"v missing translation: <code>{safe_line}</code>"
        irregular_forms = None
        translation = " ".join(remaining)

    return {
        "part_of_speech": "v",
        "german": convert_umlauts(parts[1]),
        "article": None,
        "plural": None,
        "partizip_ii": partizip_ii,
        "irregular_forms": irregular_forms,
        "translation": translation,
    }, None


def _parse_simple_line(
    pos: str, parts: list[str], safe_line: str
) -> tuple[dict | None, str | None]:
    """Parse adj or adv lines."""
    if len(parts) < 3:
        return None, f"{pos} needs: {pos} word translation: <code>{safe_line}</code>"
    return {
        "part_of_speech": pos,
        "german": convert_umlauts(parts[1]),
        "article": None,
        "plural": None,
        "partizip_ii": None,
        "irregular_forms": None,
        "translation": " ".join(parts[2:]),
    }, None


def _parse_word_line(line: str) -> tuple[dict | None, str | None]:
    """Parse a single word line. Returns (word_dict, error_message).

    Formats:
      n <article> <word> <plural> <translation...>
      v <infinitive> <partizip_ii> <translation...>                       (regular)
      vi <infinitive> <partizip_ii> <ich> <du> <er> <translation...>      (irregular)
      adj <word> <translation...>
      adv <word> <translation...>

    partizip_ii may be 1 word ("gespielt") or 2 words starting with "ist"/"hat".
    """
    line = line.strip()
    if not line:
        return None, None

    parts = line.split()
    safe_line = html.escape(line)
    if len(parts) < 3:
        return None, f"Too few fields: <code>{safe_line}</code>"

    pos = parts[0].lower()
    if pos == "n":
        return _parse_noun_line(parts, safe_line)
    if pos in ("v", "vi"):
        return _parse_verb_line(parts, is_irregular=(pos == "vi"), safe_line=safe_line)
    if pos in ("adj", "adv"):
        return _parse_simple_line(pos, parts, safe_line)

    safe_pos = html.escape(pos)
    return None, f"Unknown part of speech '{safe_pos}': <code>{safe_line}</code>"


# --- Simple commands ---


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
            "A quiz has 7 questions with mixed types:\n"
            "- Translate: type the German word\n"
            "- Multiple choice: pick the translation\n"
            "- Article: pick der/die/das (nouns)\n"
            "- Verb forms: type the asked form (irregular verbs)\n\n" + QUIZ_START_MESSAGE
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

    german = convert_umlauts(" ".join(context.args))
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


# --- /add conversation ---


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
    )
    return ADD_WORDS


async def add_words_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    conn = _get_conn(context)
    tag = context.user_data.get("add_tag", "")
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
        error_text += "\n\nFix errors and resend, or /skip to save valid lines only, or /cancel."
        await update.message.reply_text(error_text, parse_mode="HTML")
        context.user_data["parsed_words"] = parsed
        return ADD_WORDS

    if not parsed:
        await update.message.reply_text("No valid words found. Try again or /cancel.")
        return ADD_WORDS

    return await _save_words(update, context, parsed, conn, user_id, tag)


async def add_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save only the valid words, skipping errors."""
    user_id = update.effective_user.id
    conn = _get_conn(context)
    tag = context.user_data.get("add_tag", "")
    parsed = context.user_data.get("parsed_words", [])

    if not parsed:
        await update.message.reply_text("No valid words to save. /cancel to abort.")
        return ADD_WORDS

    return await _save_words(update, context, parsed, conn, user_id, tag)


async def _save_words(update, context, parsed, conn, user_id, tag) -> int:
    """Save parsed words to DB and show preview."""
    saved = []
    for w in parsed:
        try:
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
            saved.append(w)
        except ValueError as e:
            log_user_warning(logger, user_id, f"Failed to add word: {e}")
            await update.message.reply_text(f"Error: {html.escape(str(e))}")
        except Exception as e:
            log_user_error(logger, user_id, f"DB error adding word '{w.get('german')}': {e}")
            await update.message.reply_text(
                f"Could not save '{html.escape(str(w.get('german', '?')))}'. "
                "Database error — others may still be saved."
            )

    if not saved:
        await update.message.reply_text("No words were saved.")
        return ConversationHandler.END

    preview = _format_word_tables(saved)
    await update.message.reply_text(
        f"Added {len(saved)} word(s):{preview}",
        parse_mode="HTML",
    )
    _clear_add_state(context)
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_add_state(context)
    await update.message.reply_text("Add cancelled.")
    return ConversationHandler.END


# --- /quiz conversation ---


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

    tag = None
    if context.args:
        tag = context.args[0].lstrip("#")

    log_user_action(logger, user_id, f"/quiz tag={_safe_log(tag) if tag else 'all'}")

    due_words = await get_due_words(conn, user_id, limit=QUIZ_SESSION_SIZE, tag=tag)
    if not due_words:
        msg = "No words to quiz on."
        if tag:
            msg += f" (tag: #{tag})"
        msg += " Add some words first with /add."
        await update.message.reply_text(msg)
        return ConversationHandler.END

    # Collect all user words for multiple choice options
    all_user_words = []
    for pos in ("n", "v", "adj", "adv"):
        all_user_words.extend(await get_words_by_pos(conn, user_id, pos))

    session = build_quiz_session(user_id, due_words, all_user_words)
    context.user_data["quiz_session"] = session
    context.user_data["quiz_all_words"] = all_user_words

    await update.message.reply_text(QUIZ_START_MESSAGE, parse_mode="HTML")
    await _send_question(update.message, context)
    return QUIZ_ANSWERING


def _format_answer_response(question, correct: bool) -> str:
    """Build the 'Correct!/Wrong' message with HTML-escaped correct answer."""
    safe_answer = html.escape(question.correct_answer or "")
    if correct:
        return f"Correct! The answer is: <b>{safe_answer}</b>"
    return f"Wrong. The correct answer is: <b>{safe_answer}</b>"


async def quiz_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle typed answer (translate, verb_forms)."""
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
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "Quiz cancelled")
    _clear_quiz_state(context)
    await update.message.reply_text("Quiz cancelled.")
    return ConversationHandler.END


# --- Error handler ---


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


# --- Conversation handlers ---


def get_add_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_WORDS: [
                CommandHandler("skip", add_skip),
                CommandHandler("cancel", add_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_words_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )


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
