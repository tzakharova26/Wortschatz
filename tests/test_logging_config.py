import logging
import os
import tempfile
from unittest.mock import patch

from bot.logging_config import (
    UserContextFilter,
    get_logger,
    log_user_action,
    log_user_error,
    log_user_warning,
    setup_logging,
)


class TestUserContextFilter:
    def test_adds_user_id_when_missing(self):
        f = UserContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.user_id == "system"

    def test_keeps_existing_user_id(self):
        f = UserContextFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.user_id = 12345
        f.filter(record)
        assert record.user_id == 12345


class TestSetupLogging:
    def test_creates_log_dir_and_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "bot.log")
            with (
                patch("bot.logging_config.LOG_DIR", tmpdir),
                patch("bot.logging_config.LOG_FILE", log_file),
            ):
                # Clear existing handlers to avoid test pollution
                root = logging.getLogger()
                original_handlers = root.handlers[:]
                original_filters = root.filters[:]

                setup_logging()

                assert os.path.exists(tmpdir)
                # Verify a RotatingFileHandler was added
                from logging.handlers import RotatingFileHandler

                rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
                assert len(rotating_handlers) >= 1

                # Cleanup: restore original state
                for h in root.handlers[:]:
                    if h not in original_handlers:
                        root.removeHandler(h)
                        h.close()
                for f in root.filters[:]:
                    if f not in original_filters:
                        root.removeFilter(f)


class TestLogHelpers:
    def test_log_user_action(self, caplog):
        logger = get_logger("test.action")
        with caplog.at_level(logging.INFO, logger="test.action"):
            log_user_action(logger, 12345, "used /add command")
        assert "used /add command" in caplog.text

    def test_log_user_warning(self, caplog):
        logger = get_logger("test.warning")
        with caplog.at_level(logging.WARNING, logger="test.warning"):
            log_user_warning(logger, 12345, "malformed input")
        assert "malformed input" in caplog.text

    def test_log_user_error(self, caplog):
        logger = get_logger("test.error")
        with caplog.at_level(logging.ERROR, logger="test.error"):
            log_user_error(logger, 12345, "database crash", exc_info=False)
        assert "database crash" in caplog.text


class TestLogFileOutput:
    def test_writes_to_file_with_user_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            handler = logging.handlers.RotatingFileHandler(log_file, encoding="utf-8")
            formatter = logging.Formatter(
                "[%(asctime)s] %(levelname)s (user=%(user_id)s): %(message)s"
            )
            handler.setFormatter(formatter)

            logger = logging.getLogger("test.file_output")
            logger.addHandler(handler)
            logger.addFilter(UserContextFilter())
            logger.setLevel(logging.INFO)

            logger.info("test message", extra={"user_id": 42})
            handler.flush()

            with open(log_file, encoding="utf-8") as f:
                content = f.read()
            assert "user=42" in content
            assert "test message" in content

            # Cleanup
            logger.removeHandler(handler)
            handler.close()

    def test_russian_text_in_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            handler = logging.handlers.RotatingFileHandler(log_file, encoding="utf-8")
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)

            logger = logging.getLogger("test.russian")
            logger.addHandler(handler)
            logger.addFilter(UserContextFilter())
            logger.setLevel(logging.INFO)

            logger.info("Added word: Katze - кошка")
            handler.flush()

            with open(log_file, encoding="utf-8") as f:
                content = f.read()
            assert "кошка" in content

            # Cleanup
            logger.removeHandler(handler)
            handler.close()
