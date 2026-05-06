import aiosqlite
import pytest

from bot.database import SCHEMA


@pytest.fixture
async def db():
    """Provide an in-memory SQLite connection with schema initialized."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    yield conn
    await conn.close()
