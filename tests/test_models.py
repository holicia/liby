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


@pytest.mark.asyncio
async def test_init_db_creates_api_costs_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_costs'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_init_db_creates_projects_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_adds_project_id_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "project_id" in cols


@pytest.mark.asyncio
async def test_init_db_migrates_existing_items_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, title TEXT NOT NULL)"
        )
        await db.commit()
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "project_id" in cols


@pytest.mark.asyncio
async def test_init_db_adds_timeline_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "timeline" in cols


@pytest.mark.asyncio
async def test_init_db_adds_paragraphs_column_idempotently(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "t.db")
    await init_db(db_path)
    await init_db(db_path)  # 두 번째 호출에서도 에러 없이 통과해야 함
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cur.fetchall()]
    assert "paragraphs" in cols


@pytest.mark.asyncio
async def test_init_db_adds_transcript_segments_column_idempotently(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "t.db")
    await init_db(db_path)
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cur.fetchall()]
    assert "transcript_segments" in cols
