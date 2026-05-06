import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "data"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3


class UserContextFilter(logging.Filter):
    """Adds user_id to log records if not already present."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "user_id"):
            record.user_id = "system"
        return True


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s (user=%(user_id)s): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    context_filter = UserContextFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addFilter(context_filter)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_user_action(logger: logging.Logger, user_id: int, message: str) -> None:
    logger.info(message, extra={"user_id": user_id})


def log_user_warning(logger: logging.Logger, user_id: int, message: str) -> None:
    logger.warning(message, extra={"user_id": user_id})


def log_user_error(
    logger: logging.Logger, user_id: int, message: str, exc_info: bool = True
) -> None:
    logger.error(message, extra={"user_id": user_id}, exc_info=exc_info)
