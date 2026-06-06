import pytest
import config
from services import discord_bot as db


@pytest.fixture(autouse=True)
def _allow(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_ALLOWED_USER_ID", "111")


class Recorder:
    def __init__(self):
        self.calls = []
    async def __call__(self, text=None, embed=None):
        self.calls.append({"text": text, "embed": embed})


@pytest.mark.asyncio
async def test_ignores_other_users(monkeypatch):
    called = {"n": 0}
    async def fake_submit(*a, **k):
        called["n"] += 1
        return {"task_id": "x", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    rec = Recorder()
    await db.handle_message(999, "메모", rec)   # 허용 ID 아님
    assert called["n"] == 0
    assert rec.calls == []


@pytest.mark.asyncio
async def test_ignores_bot_messages(monkeypatch):
    rec = Recorder()
    await db.handle_message(111, "메모", rec, is_bot=True)
    assert rec.calls == []


@pytest.mark.asyncio
async def test_happy_path_done_replies_embed(monkeypatch):
    async def fake_submit(text, mode="quick", project_id=None):
        assert mode == "quick"
        return {"task_id": "tid", "title": "t", "kind": "youtube"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)

    class FakeTask:
        status = "done"; note_id = 5; error = None
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())

    async def fake_payload(nid):
        assert nid == 5
        return {"embed": {"title": "제목"}, "read_url": "http://x/5/read"}
    monkeypatch.setattr(db.bot_core, "note_payload", fake_payload)

    rec = Recorder()
    await db.handle_message(111, "https://youtu.be/dQw4w9WgXcQ", rec)
    assert any(c["embed"] for c in rec.calls)
    assert rec.calls[-1]["embed"]["title"] == "제목"


@pytest.mark.asyncio
async def test_detailed_keyword_prefix(monkeypatch):
    seen = {}
    async def fake_submit(text, mode="quick", project_id=None):
        seen["mode"] = mode; seen["text"] = text
        return {"task_id": "tid", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    class FakeTask:
        status = "error"; note_id = None; error = "x"
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())
    rec = Recorder()
    await db.handle_message(111, "상세 https://youtu.be/dQw4w9WgXcQ", rec)
    assert seen["mode"] == "detailed"
    assert seen["text"] == "https://youtu.be/dQw4w9WgXcQ"  # 키워드 제거됨


@pytest.mark.asyncio
async def test_error_status_replies_failure(monkeypatch):
    async def fake_submit(*a, **k):
        return {"task_id": "tid", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    class FakeTask:
        status = "error"; note_id = None; error = "분석 폭발"
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())
    rec = Recorder()
    await db.handle_message(111, "메모", rec)
    assert any("분석 폭발" in (c["text"] or "") for c in rec.calls)
