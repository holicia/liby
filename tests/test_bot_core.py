import pytest
import config
from models import init_db
from services import task_queue as tq
from services import bot_core


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    db_path = str(tmp_path / "b.db")
    await init_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://pc.ts.net:8000")
    monkeypatch.setattr(config, "DEFAULT_AI_PROVIDER", "claude-cli")
    tq._reset_for_tests()
    import routers.youtube, routers.text  # noqa: F401  builder 등록
    yield db_path
    tq._reset_for_tests()


@pytest.mark.asyncio
async def test_submit_analysis_detects_youtube():
    out = await bot_core.submit_analysis("https://youtu.be/dQw4w9WgXcQ")
    assert out["kind"] == "youtube"
    task = tq.get_task(out["task_id"])
    assert task.source_type == "youtube"
    assert task.spec["url"] == "https://youtu.be/dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_submit_analysis_falls_back_to_text():
    out = await bot_core.submit_analysis("그냥 메모 텍스트입니다", mode="detailed")
    assert out["kind"] == "text"
    task = tq.get_task(out["task_id"])
    assert task.source_type == "text"
    assert task.spec["mode"] == "detailed"
    assert task.spec["content"] == "그냥 메모 텍스트입니다"


@pytest.mark.asyncio
async def test_submit_analysis_empty_raises():
    with pytest.raises(ValueError):
        await bot_core.submit_analysis("   ")


@pytest.mark.asyncio
async def test_note_payload_builds_embed_with_read_url(_isolated):
    import aiosqlite, json
    async with aiosqlite.connect(_isolated) as db:
        cur = await db.execute(
            "INSERT INTO items(type,title,summary,tags,source_url) "
            "VALUES('youtube','제목','요약',?,?)",
            (json.dumps(["투자"]), "https://youtu.be/vid12345678"),
        )
        await db.commit()
        nid = cur.lastrowid
    payload = await bot_core.note_payload(nid)
    assert payload["read_url"] == f"http://pc.ts.net:8000/api/items/{nid}/read"
    assert payload["embed"]["title"] == "제목"
    assert payload["embed"]["url"].endswith(f"/api/items/{nid}/read")


@pytest.mark.asyncio
async def test_note_payload_missing_returns_none():
    assert await bot_core.note_payload(99999) is None
