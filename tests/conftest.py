from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from bot.database import _apply_schema


@pytest.fixture
async def db():
    """In-memory SQLite connection initialized via the same code path as
    production (SCHEMA + _migrate). Using ``init_db(":memory:")`` directly
    doesn't work because SQLite's in-memory DB is per-connection — it would
    vanish when init_db closed its own connection. Instead we mirror the
    flow: open the connection here, then apply the same schema/migrations
    helper init_db uses, so future migrations get test coverage automatically.
    """
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    await _apply_schema(conn)
    yield conn
    await conn.close()


@pytest.fixture
def fake_update():
    """Factory for a fake telegram Update with mocked async methods."""

    def _make(user_id=12345, text=None, callback_data=None):
        upd = MagicMock()
        upd.effective_user.id = user_id
        if text is not None or callback_data is None:
            upd.message = MagicMock()
            upd.message.text = text
            upd.message.reply_text = AsyncMock()
            upd.effective_message = upd.message
        else:
            upd.message = None
        if callback_data is not None:
            upd.callback_query = MagicMock()
            upd.callback_query.data = callback_data
            upd.callback_query.answer = AsyncMock()
            upd.callback_query.edit_message_text = AsyncMock()
            upd.callback_query.edit_message_reply_markup = AsyncMock()
            upd.callback_query.message = MagicMock()
            upd.callback_query.message.reply_text = AsyncMock()
            upd.effective_message = upd.callback_query.message
        else:
            upd.callback_query = None
        return upd

    return _make


@pytest.fixture
def fake_context(db):
    """A fake Telegram context with bot_data, user_data, args."""
    ctx = MagicMock()
    ctx.bot_data = {"db_conn": db}
    ctx.user_data = {}
    ctx.args = []
    return ctx
