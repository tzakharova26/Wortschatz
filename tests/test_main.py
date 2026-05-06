from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.main import main, post_init, post_shutdown


class TestPostInit:
    async def test_initializes_db_and_stores_conn(self):
        app = MagicMock()
        app.bot_data = {}
        with (
            patch("bot.main.init_db", new_callable=AsyncMock) as init_mock,
            patch("bot.main.get_connection", new_callable=AsyncMock) as get_mock,
            patch("bot.main.load_all_reminders", new_callable=AsyncMock) as load_mock,
        ):
            fake_conn = MagicMock()
            get_mock.return_value = fake_conn
            await post_init(app)
            init_mock.assert_awaited_once()
            load_mock.assert_awaited_once()
            assert app.bot_data["db_conn"] is fake_conn


class TestPostShutdown:
    async def test_closes_connection(self):
        app = MagicMock()
        fake_conn = AsyncMock()
        app.bot_data = {"db_conn": fake_conn}
        await post_shutdown(app)
        fake_conn.close.assert_awaited_once()

    async def test_no_connection_does_not_crash(self):
        app = MagicMock()
        app.bot_data = {}
        # Should not raise
        await post_shutdown(app)


class TestMain:
    def test_missing_token_raises(self):
        with (
            patch("bot.main.load_dotenv"),
            patch("bot.main.setup_logging"),
            patch("bot.main.os.getenv", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="BOT_TOKEN"):
                main()

    def test_with_token_builds_app(self):
        with (
            patch("bot.main.load_dotenv"),
            patch("bot.main.setup_logging"),
            patch("bot.main.os.getenv", return_value="fake-token"),
            patch("bot.main.ApplicationBuilder") as builder_mock,
        ):
            fake_app = MagicMock()
            chain = builder_mock.return_value.token.return_value
            chain.post_init.return_value.post_shutdown.return_value.build.return_value = fake_app
            main()
            # Verify token was set
            builder_mock.return_value.token.assert_called_once_with("fake-token")
            # Verify run_polling was called
            fake_app.run_polling.assert_called_once()
