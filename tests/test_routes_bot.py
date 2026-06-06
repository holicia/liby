import json
import pytest
import aiosqlite
import config
from httpx import AsyncClient, ASGITransport
from main import app
from models import init_db
from services import task_queue as tq


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://pc.ts.net:8000")
    monkeypatch.setattr(config, "BOT_API_TOKEN", "")
    tq._reset_for_tests()
    import routers.youtube, routers.text  # noqa: F401
    yield db_path
    tq._reset_for_tests()


@pytest.mark.asyncio
async def test_analyze_youtube_returns_task_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "https://youtu.be/dQw4w9WgXcQ"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "youtube"
    assert tq.get_task(body["task_id"]).source_type == "youtube"


@pytest.mark.asyncio
async def test_analyze_empty_input_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_task_status_json():
    out = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        out = (await c.post("/api/bot/analyze", json={"input": "메모"})).json()
        resp = await c.get(f"/api/bot/tasks/{out['task_id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("queued", "running", "done", "error")


@pytest.mark.asyncio
async def test_task_status_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/bot/tasks/deadbeef")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_note_json_includes_embed_and_read_url(_isolated):
    async with aiosqlite.connect(_isolated) as db:
        cur = await db.execute(
            "INSERT INTO items(type,title,summary,source_url) "
            "VALUES('youtube','제목','요약','https://youtu.be/vid12345678')",
        )
        await db.commit()
        nid = cur.lastrowid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/bot/notes/{nid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read_url"].endswith(f"/api/items/{nid}/read")
    assert body["embed"]["title"] == "제목"


@pytest.mark.asyncio
async def test_token_guard_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(config, "BOT_API_TOKEN", "secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "메모"})
    assert resp.status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.post("/api/bot/analyze", json={"input": "메모"},
                          headers={"X-Bot-Token": "secret"})
    assert ok.status_code == 200
