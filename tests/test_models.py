import pytest
import aiosqlite
from models import init_db, get_db


@pytest.mark.asyncio
async def test_init_db_creates_items_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_init_db_creates_settings_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        )
        row = await cursor.fetchone()
    assert row is not None
