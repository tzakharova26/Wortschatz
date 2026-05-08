"""Shared test fixtures.

The Update/Context fakes used to be ``MagicMock(...)``. That accepted *any*
attribute access without complaint, so a typo like ``update.callback_qury``
would silently succeed in a test while failing at runtime. The dataclass
fakes below mirror only the API surface our handlers actually use; an
unexpected attribute access raises ``AttributeError`` and surfaces the bug.
``AsyncMock`` is still used for the awaitable methods (``reply_text``,
``edit_message_text``, etc.) because tests assert on ``.call_args`` /
``await_args_list`` against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

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


@dataclass
class FakeUser:
    id: int = 12345


@dataclass
class FakeMessage:
    text: str | None = None
    reply_text: AsyncMock = field(default_factory=AsyncMock)


@dataclass
class FakeCallbackQuery:
    data: str | None = None
    message: FakeMessage = field(default_factory=FakeMessage)
    answer: AsyncMock = field(default_factory=AsyncMock)
    edit_message_text: AsyncMock = field(default_factory=AsyncMock)
    edit_message_reply_markup: AsyncMock = field(default_factory=AsyncMock)


@dataclass
class FakeUpdate:
    """Mimics ``telegram.Update``. Exactly one of ``message`` / ``callback_query``
    is populated to match how PTB delivers updates; ``effective_message`` aliases
    whichever message exists so handlers can reply uniformly."""

    effective_user: FakeUser
    message: FakeMessage | None
    callback_query: FakeCallbackQuery | None
    effective_message: FakeMessage


@dataclass
class FakeContext:
    """Mimics ``telegram.ext.ContextTypes.DEFAULT_TYPE``. ``application`` is only
    populated in tests that exercise PTB's JobQueue (e.g. /remindme); most
    handler tests leave it ``None``."""

    bot_data: dict[str, Any]
    user_data: dict[str, Any] = field(default_factory=dict)
    args: list[str] = field(default_factory=list)
    error: BaseException | None = None
    application: Any = None


@pytest.fixture
def fake_update():
    """Factory for a FakeUpdate. ``text`` populates ``update.message.text``;
    ``callback_data`` switches the update into a callback-query shape (with
    ``update.callback_query.data``). The two are mutually exclusive — matches
    the real PTB Update topology."""

    def _make(
        user_id: int = 12345,
        text: str | None = None,
        callback_data: str | None = None,
    ) -> FakeUpdate:
        user = FakeUser(id=user_id)
        if callback_data is None:
            msg = FakeMessage(text=text)
            return FakeUpdate(
                effective_user=user,
                message=msg,
                callback_query=None,
                effective_message=msg,
            )
        cb_msg = FakeMessage()
        cb = FakeCallbackQuery(data=callback_data, message=cb_msg)
        return FakeUpdate(
            effective_user=user,
            message=None,
            callback_query=cb,
            effective_message=cb_msg,
        )

    return _make


@pytest.fixture
def fake_context(db):
    """Fresh per-test FakeContext wired to the in-memory DB."""
    return FakeContext(bot_data={"db_conn": db})
