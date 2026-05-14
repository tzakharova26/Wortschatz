"""Contact-owner flow: direct contact info plus anonymous letter forwarding."""

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

from bot.config import MAX_OWNER_MESSAGE_CHARS, get_owner_tg_nickname, get_owner_user_id
from bot.i18n import normalize_language
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning

from ._shared import CB_OWNER, CONTACT_WRITING, _get_lang, _safe_log

logger = get_logger(__name__)


def _owner_label() -> str:
    nickname = get_owner_tg_nickname()
    if not nickname:
        return "the owner"
    if not nickname.startswith("@"):
        nickname = "@" + nickname
    return nickname


def _contact_text(lang: str = "en") -> str:
    lang = normalize_language(lang)
    owner = html.escape(_owner_label())
    if lang == "ru":
        return (
            "<b>Связаться с владельцем</b>\n\n"
            f"Если хочешь, можешь написать владельцу напрямую: <b>{owner}</b>.\n\n"
            "Также можно написать письмо здесь. Бот перешлет его владельцу "
            "анонимно, без информации об отправителе."
        )
    return (
        "<b>Contact the owner</b>\n\n"
        f"If you want, you can directly contact the owner: <b>{owner}</b>.\n\n"
        "You can also write a letter here. The bot will redirect it to the owner "
        "anonymously, without sender info."
    )


def _contact_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    text = (
        "Написать анонимное письмо"
        if normalize_language(lang) == "ru"
        else "Write anonymous letter"
    )
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=f"{CB_OWNER}write")]])


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = await _get_lang(context, user_id)
    log_user_action(logger, user_id, "/contact")
    await update.message.reply_text(
        _contact_text(lang),
        parse_mode="HTML",
        reply_markup=_contact_keyboard(lang),
    )
    return ConversationHandler.END


async def contact_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = await _get_lang(context, user_id)
    action = (query.data or "").removeprefix(CB_OWNER)

    if action == "info":
        log_user_action(logger, user_id, "Contact owner info opened")
        await query.edit_message_text(
            _contact_text(lang),
            parse_mode="HTML",
            reply_markup=_contact_keyboard(lang),
        )
        return ConversationHandler.END

    if action != "write":
        log_user_warning(logger, user_id, f"Unknown contact callback: {_safe_log(action)}")
        return ConversationHandler.END

    log_user_action(logger, user_id, "Anonymous owner letter started")
    await query.edit_message_text(
        (
            "Напиши письмо следующим сообщением. Оно будет отправлено владельцу анонимно.\n\n"
            "Отправь /cancel, чтобы остановиться."
            if lang == "ru"
            else "Write your letter in the next message. It will be sent to the owner "
            "anonymously.\n\n"
            "Send /cancel to stop."
        ),
    )
    return CONTACT_WRITING


async def contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = await _get_lang(context, user_id)
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text(
            "Пустое сообщение не отправлено. Напиши текст или /cancel."
            if lang == "ru"
            else "Empty message was not sent. Write a message or /cancel."
        )
        return CONTACT_WRITING
    if len(text) > MAX_OWNER_MESSAGE_CHARS:
        log_user_warning(
            logger,
            user_id,
            f"Owner letter too long: len={len(text)}, limit={MAX_OWNER_MESSAGE_CHARS}",
        )
        await update.message.reply_text(
            (
                f"Сообщение слишком длинное ({len(text)} символов). Максимум: "
                f"{MAX_OWNER_MESSAGE_CHARS}. Ничего не отправлено."
            )
            if lang == "ru"
            else f"Your message is too long ({len(text)} characters). Maximum is "
            f"{MAX_OWNER_MESSAGE_CHARS}. Nothing was sent."
        )
        return CONTACT_WRITING

    owner_id = get_owner_user_id()
    if owner_id is None:
        log_user_warning(logger, user_id, "Owner letter not sent: OWNER_USER_ID missing/invalid")
        await update.message.reply_text(
            (
                "Анонимные письма пока не настроены. Напиши владельцу напрямую: "
                f"{html.escape(_owner_label())}."
            )
            if lang == "ru"
            else "Anonymous letters are not configured yet. Please contact the owner directly: "
            f"{html.escape(_owner_label())}."
        )
        return ConversationHandler.END

    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text="<b>Anonymous letter from Wortschatz user</b>\n\n" + html.escape(text),
            parse_mode="HTML",
        )
    except Exception as e:
        log_user_error(logger, user_id, f"Failed to send anonymous owner letter: {e}", exc_info=e)
        await update.message.reply_text(
            "Не удалось отправить сообщение. Попробуй позже."
            if lang == "ru"
            else "Could not send the message. Please try again later."
        )
        return ConversationHandler.END

    log_user_action(logger, user_id, "Anonymous owner letter sent")
    await update.message.reply_text(
        "Сообщение отправлено анонимно." if lang == "ru" else "Your message was sent anonymously."
    )
    return ConversationHandler.END


async def contact_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(logger, update.effective_user.id, "Anonymous owner letter cancelled")
    lang = await _get_lang(context, update.effective_user.id)
    await update.message.reply_text("Сообщение отменено." if lang == "ru" else "Message cancelled.")
    return ConversationHandler.END


def get_contact_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("contact", contact_command),
            CallbackQueryHandler(contact_callback, pattern=f"^{CB_OWNER}"),
        ],
        states={
            CONTACT_WRITING: [
                CommandHandler("cancel", contact_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, contact_message),
            ],
        },
        fallbacks=[CommandHandler("cancel", contact_cancel)],
    )
