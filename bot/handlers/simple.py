"""Simple one-shot commands plus the global error handler."""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import LIST_MAX_WORDS, get_owner_user_id
from bot.database import (
    delete_word,
    find_words_by_german,
    get_tags,
    get_words,
    set_user_language,
)
from bot.health import collect_health_snapshot, format_health_snapshot
from bot.i18n import (
    SUPPORTED_LANGUAGES,
    add_format_message,
    commands_help,
    quiz_start_message,
    start_message,
    t,
)
from bot.logging_config import get_logger, log_user_action, log_user_error
from bot.stats import build_stats_chart_file, get_user_stats

from ._shared import (
    CB_HELP,
    CB_LANG,
    CB_OWNER,
    PENDING_DELETE_TTL_S,
    _format_word_tables,
    _get_conn,
    _get_lang,
    _safe_log,
    pending_pop,
    pending_set,
)

logger = get_logger(__name__)


# Help/start text — kept here because they reference each other and the
# ADD_FORMAT_MESSAGE constant from /add. The HTML escapes (e.g. &lt;id|all&gt;)
# are deliberate; without them Telegram rejects the message.
COMMANDS_HELP = commands_help("en")
START_MESSAGE = start_message("en")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/start")
    await update.message.reply_text(
        "Welcome to Wortschatz. Please choose your interface language.\n\n"
        "Добро пожаловать в Wortschatz. Пожалуйста, выбери язык интерфейса.",
        reply_markup=_language_keyboard(source="start"),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/help")
    lang = await _get_lang(context, user_id)
    keyboard = [
        [
            InlineKeyboardButton(t("btn_commands", lang), callback_data=f"{CB_HELP}commands"),
            InlineKeyboardButton(t("btn_add", lang), callback_data=f"{CB_HELP}add"),
        ],
        [
            InlineKeyboardButton(t("btn_practice", lang), callback_data=f"{CB_HELP}practice"),
            InlineKeyboardButton(t("btn_contact", lang), callback_data=f"{CB_OWNER}info"),
            InlineKeyboardButton(t("btn_language", lang), callback_data=f"{CB_LANG}menu"),
        ],
    ]
    await update.message.reply_text(
        t("help_prompt", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = await _get_lang(context, user_id)
    topic = query.data.removeprefix(CB_HELP)

    if query.data and query.data.startswith(CB_OWNER):
        from .contact import _contact_keyboard, _contact_text

        await query.edit_message_text(
            _contact_text(lang),
            parse_mode="HTML",
            reply_markup=_contact_keyboard(lang),
        )
        return

    if topic == "commands":
        text = commands_help(lang)
    elif topic == "add":
        text = add_format_message(lang)
    elif topic == "practice":
        text = t("practice_help", lang) + quiz_start_message(lang)
    else:
        text = t("unknown_topic", lang)

    await query.edit_message_text(text, parse_mode="HTML")


def _language_keyboard(source: str | None = None) -> InlineKeyboardMarkup:
    prefix = f"{CB_LANG}{source}:" if source else CB_LANG
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(label, callback_data=f"{prefix}{code}")
                for code, label in SUPPORTED_LANGUAGES.items()
            ]
        ]
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/language {_safe_log(' '.join(context.args or []))}")
    lang = await _get_lang(context, user_id)
    if context.args:
        requested = context.args[0].lower()
        if requested in ("english", "en"):
            requested = "en"
        elif requested in ("russian", "русский", "ru"):
            requested = "ru"
        if requested not in SUPPORTED_LANGUAGES:
            await update.message.reply_text(t("language_invalid", lang))
            return
        await set_user_language(_get_conn(context), user_id, requested)
        context.user_data["language"] = requested
        await update.message.reply_text(t("language_set", requested))
        return
    await update.message.reply_text(t("language_prompt", lang), reply_markup=_language_keyboard())


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    current_lang = await _get_lang(context, user_id)
    action = (query.data or "").removeprefix(CB_LANG)
    if action == "menu":
        await query.edit_message_text(
            t("language_prompt", current_lang),
            reply_markup=_language_keyboard(),
        )
        return
    from_start = False
    if action.startswith("start:"):
        from_start = True
        action = action.removeprefix("start:")
    lang = action
    if lang not in SUPPORTED_LANGUAGES:
        await query.edit_message_text(t("language_invalid", current_lang))
        return
    await set_user_language(_get_conn(context), user_id, lang)
    context.user_data["language"] = lang
    if from_start:
        await query.edit_message_text(start_message(lang), parse_mode="HTML")
    else:
        await query.edit_message_text(t("language_set", lang))


async def tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/tags")
    conn = _get_conn(context)
    lang = await _get_lang(context, user_id)
    tags = await get_tags(conn, user_id)
    if not tags:
        await update.message.reply_text(t("no_tags", lang))
        return
    await update.message.reply_text(
        t("your_tags", lang) + "\n" + "\n".join(f"  #{tag}" for tag in tags)
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/list {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)
    lang = await _get_lang(context, user_id)

    if not context.args:
        await update.message.reply_text(t("list_need_tag", lang))
        return

    tag = context.args[0].lstrip("#")
    words = await get_words(conn, user_id, tag=tag)
    if not words:
        await update.message.reply_text(t("list_empty", lang, tag=tag))
        return

    total = len(words)
    truncated = total > LIST_MAX_WORDS
    words = words[:LIST_MAX_WORDS]
    safe_tag = html.escape(tag)
    text = t("list_header", lang, tag=safe_tag, total=total)
    text += _format_word_tables(words, lang=lang)
    if truncated:
        text += f"\n\n{t('list_more', lang, count=total - LIST_MAX_WORDS)}"

    await update.message.reply_text(text, parse_mode="HTML")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, f"/delete {_safe_log(' '.join(context.args or []))}")
    conn = _get_conn(context)
    lang = await _get_lang(context, user_id)

    # Clear any stale pending_delete from a previous call (also drops it if expired)
    pending_pop(context, "pending_delete")

    if not context.args:
        await update.message.reply_text(t("delete_usage", lang))
        return

    german = " ".join(context.args)
    matches = await find_words_by_german(conn, user_id, german)

    if not matches:
        await update.message.reply_text(t("delete_not_found", lang, word=german))
        return

    if len(matches) > 1:
        lines = [t("delete_multi", lang, word=german)]
        for w in matches:
            pos = w["part_of_speech"]
            lines.append(f"  [{w['id']}] {pos}: {w['german']} — {w['translation']}")
        lines.append("\n" + t("delete_confirm", lang))
        pending_set(context, "pending_delete", [w["id"] for w in matches], ttl=PENDING_DELETE_TTL_S)
        await update.message.reply_text("\n".join(lines))
        return

    word = matches[0]
    deleted = await delete_word(conn, user_id, word["id"])
    if deleted:
        await update.message.reply_text(
            t("delete_done", lang, word=word["german"], translation=word["translation"])
        )
    else:
        await update.message.reply_text(t("delete_failed", lang))


async def delete_confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/delete_confirm")
    conn = _get_conn(context)
    lang = await _get_lang(context, user_id)

    pending = pending_pop(context, "pending_delete")
    if not pending:
        await update.message.reply_text(t("delete_nothing", lang))
        return

    count = 0
    for word_id in pending:
        if await delete_word(conn, user_id, word_id):
            count += 1

    await update.message.reply_text(t("delete_count", lang, count=count))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/stats")
    conn = _get_conn(context)
    lang = await _get_lang(context, user_id)
    text = await get_user_stats(conn, user_id, lang=lang)
    await update.message.reply_text(text, parse_mode="HTML")
    chart = await build_stats_chart_file(conn, user_id, lang=lang)
    caption = "График активности" if lang == "ru" else "Activity chart"
    await update.message.reply_photo(photo=chart, caption=caption)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    log_user_action(logger, user_id, "/health")
    lang = await _get_lang(context, user_id)
    owner_id = get_owner_user_id()
    if owner_id is None:
        logger.warning(
            "Health command refused: OWNER_USER_ID missing/invalid",
            extra={"user_id": user_id},
        )
        text = (
            "Команда /health доступна только владельцу, но OWNER_USER_ID не настроен."
            if lang == "ru"
            else "/health is owner-only, but OWNER_USER_ID is not configured."
        )
        await update.message.reply_text(text)
        return
    if user_id != owner_id:
        logger.warning(
            "Health command refused: user is not owner",
            extra={"user_id": user_id},
        )
        text = (
            "Команда /health доступна только владельцу."
            if lang == "ru"
            else "/health is available only to the owner."
        )
        await update.message.reply_text(text)
        return

    snapshot = await collect_health_snapshot(_get_conn(context), owner_id)
    await update.message.reply_text(format_health_snapshot(snapshot, lang), parse_mode="HTML")


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
                t("error_generic", await _get_lang(context, user_id))
            )
        except Exception as e:
            logger.error("Failed to send error message to user: %s", e, extra={"user_id": user_id})
