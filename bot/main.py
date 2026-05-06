import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from bot.database import get_connection, init_db
from bot.handlers import (
    CB_HELP,
    delete_command,
    delete_confirm_command,
    error_handler,
    get_add_conversation,
    get_quiz_conversation,
    help_callback,
    help_command,
    list_command,
    start_command,
    stats_command,
    tags_command,
)
from bot.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


async def post_init(application) -> None:
    """Initialize DB and store connection in bot_data."""
    await init_db()
    conn = await get_connection()
    application.bot_data["db_conn"] = conn
    logger.info("Bot started", extra={"user_id": "system"})


async def post_shutdown(application) -> None:
    """Close DB connection on shutdown."""
    conn = application.bot_data.get("db_conn")
    if conn:
        await conn.close()
    logger.info("Bot stopped", extra={"user_id": "system"})


def main() -> None:
    load_dotenv()
    setup_logging()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set in environment")

    app = (
        ApplicationBuilder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    )

    # Conversation handlers (must be added before simple handlers)
    app.add_handler(get_add_conversation())
    app.add_handler(get_quiz_conversation())

    # Simple commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("tags", tags_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("delete_confirm", delete_confirm_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Help callback buttons
    app.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CB_HELP}"))

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Starting bot polling", extra={"user_id": "system"})
    app.run_polling()


if __name__ == "__main__":
    main()
