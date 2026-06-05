"""project digest — storage round-trip + build_project_digest + 라우터."""
import json
from unittest.mock import AsyncMock, patch

import pytest
import aiosqlite
from httpx import AsyncClient, ASGITransport

import config
from main import app
from models import init_db
from services import storage


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    db_path = str(tmp_path / "d.db")
    await init_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")
    yield db_path


async def _insert_project(db_path: str, name: str = "P") -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("INSERT INTO projects(name) VALUES(?)", (name,))
        await db.commit()
        return cur.lastrowid


async def _insert_note(db_path: str, project_id: int, title: str,
                       summary: str = "요약", sections=None, tags=None) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "INSERT INTO items(type,title,summary,sections,tags,project_id,ai_provider) "
            "VALUES('youtube',?,?,?,?,?,'claude-cli')",
            (title, summary, json.dumps(sections or []), json.dumps(tags or []), project_id),
        )
        await db.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_save_get_project_digest_round_trip(_isolated):
    pid = await _insert_project(_isolated)
    await _insert_note(_isolated, pid, "n1")
    await _insert_note(_isolated, pid, "n2")
    digest = {"title": "T", "summary": "S", "insights": ["i"], "clusters": []}
    await storage.save_project_digest(_isolated, pid, digest, note_count=2,
                                      provider="claude-cli", model="claude")
    out = await storage.get_project_digest(_isolated, pid)
    assert out["digest"] == digest
    assert out["note_count"] == 2
    assert out["provider"] == "claude-cli"
    assert out["is_stale"] is False
    assert out["current_note_count"] == 2


@pytest.mark.asyncio
async def test_get_project_digest_marks_stale_when_notes_added(_isolated):
    pid = await _insert_project(_isolated)
    await _insert_note(_isolated, pid, "n1")
    await storage.save_project_digest(_isolated, pid, {"title": "t"}, note_count=1,
                                      provider="claude-cli", model="claude")
    await _insert_note(_isolated, pid, "n2")  # 노트 추가
    out = await storage.get_project_digest(_isolated, pid)
    assert out["is_stale"] is True
    assert out["current_note_count"] == 2


@pytest.mark.asyncio
async def test_get_project_digest_none_when_missing(_isolated):
    pid = await _insert_project(_isolated)
    assert await storage.get_project_digest(_isolated, pid) is None


@pytest.mark.asyncio
async def test_list_notes_for_digest_returns_slim_fields(_isolated):
    pid = await _insert_project(_isolated)
    sec = [{"heading": "h1", "subsections": [{"heading": "s1"}]}]
    nid = await _insert_note(_isolated, pid, "title1", summary="요약1",
                             sections=sec, tags=["t1"])
    notes = await storage.list_notes_for_digest(_isolated, pid)
    assert len(notes) == 1
    assert notes[0]["id"] == nid
    assert notes[0]["sections"] == sec
    assert notes[0]["tags"] == ["t1"]


@pytest.mark.asyncio
async def test_build_project_digest_parses_llm_json(monkeypatch):
    from services import digest as dg
    from services.ai import bridge_client as bc
    fake = AsyncMock(return_value=bc.BridgeRunResult(
        summary=json.dumps({
            "title": "AI 학습",
            "summary": "두 노트 종합",
            "insights": ["깨달음1", "깨달음2"],
            "clusters": [{"theme": "기초", "note_ids": [1, 2], "description": "기초 모음"}],
        }, ensure_ascii=False),
        session_id=None, usage=bc.BridgeUsage(),
    ))
    monkeypatch.setattr(bc, "run_agent", fake)
    monkeypatch.setattr(config, "BRIDGE_CWD", "/workspace")
    notes = [
        {"id": 1, "title": "N1", "summary": "s1", "sections": [], "tags": []},
        {"id": 2, "title": "N2", "summary": "s2", "sections": [], "tags": []},
    ]
    result, model = await dg.build_project_digest(notes, adapter="claude")
    assert result["title"] == "AI 학습"
    assert result["insights"] == ["깨달음1", "깨달음2"]
    assert result["clusters"][0]["note_ids"] == [1, 2]
    assert model == "claude"


@pytest.mark.asyncio
async def test_build_project_digest_empty_notes_raises():
    from services import digest as dg
    with pytest.raises(ValueError, match="노트가 없습니다"):
        await dg.build_project_digest([], adapter="claude")


@pytest.mark.asyncio
async def test_route_get_digest_returns_button_when_no_cache(_isolated):
    pid = await _insert_project(_isolated)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/projects/{pid}/digest")
    assert resp.status_code == 200
    assert "정리하기" in resp.text
    assert f"/api/projects/{pid}/digest" in resp.text


@pytest.mark.asyncio
async def test_route_post_digest_400_when_empty_project(_isolated):
    pid = await _insert_project(_isolated)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/projects/{pid}/digest", data={"provider": "claude-cli"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_route_post_digest_rejects_unsupported_provider(_isolated):
    pid = await _insert_project(_isolated)
    await _insert_note(_isolated, pid, "n1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/projects/{pid}/digest", data={"provider": "claude"})  # API direct not allowed here
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_route_post_digest_success_caches_and_returns_panel(_isolated, monkeypatch):
    pid = await _insert_project(_isolated)
    await _insert_note(_isolated, pid, "n1", summary="s1")
    fake_digest = {
        "title": "투자 정리",
        "summary": "한 줄 요약",
        "insights": ["통찰A"],
        "clusters": [],
    }
    async def fake_build(notes, *, adapter, **kw):
        return fake_digest, adapter
    monkeypatch.setattr("services.digest.build_project_digest", fake_build)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/projects/{pid}/digest", data={"provider": "claude-cli"})
    assert resp.status_code == 200
    assert "투자 정리" in resp.text
    assert "통찰A" in resp.text
    # DB에 캐싱됐는지
    cached = await storage.get_project_digest(_isolated, pid)
    assert cached["digest"] == fake_digest
    assert cached["provider"] == "claude-cli"
