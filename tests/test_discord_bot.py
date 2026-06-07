import pytest
import config
from services import discord_bot as db


@pytest.fixture(autouse=True)
def _allow(monkeypatch):
    # 권한은 전용 채널 기준 — 허용 채널 id를 111로 둔다.
    monkeypatch.setattr(config, "DISCORD_CHANNEL_ID", "111")


class Recorder:
    def __init__(self):
        self.calls = []
    async def __call__(self, text=None, embed=None):
        self.calls.append({"text": text, "embed": embed})


@pytest.mark.asyncio
async def test_ignores_other_channels(monkeypatch):
    called = {"n": 0}
    async def fake_submit(*a, **k):
        called["n"] += 1
        return {"task_id": "x", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    rec = Recorder()
    await db.handle_message(999, "메모", rec)   # 허용 채널 아님
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


def test_parse_mode_requires_word_boundary():
    # 일반 단어를 명령으로 오인하지 않는다
    assert db._parse_mode("detailed notes from today") == ("quick", "detailed notes from today")
    assert db._parse_mode("상세분석이 필요한 메모") == ("quick", "상세분석이 필요한 메모")
    # 명시적 명령 형태만 detailed
    assert db._parse_mode("상세 https://youtu.be/x") == ("detailed", "https://youtu.be/x")
    assert db._parse_mode("/detailed https://youtu.be/x") == ("detailed", "https://youtu.be/x")
    # 키워드만 단독이면 명령 아님(분석할 내용 없음)
    assert db._parse_mode("상세") == ("quick", "상세")


@pytest.mark.asyncio
async def test_legit_text_starting_with_detailed_is_quick(monkeypatch):
    """'detailed'로 시작하는 평범한 메모는 quick으로, 원문 보존되어 분석된다."""
    seen = {}
    async def fake_submit(text, mode="quick", project_id=None):
        seen["mode"] = mode; seen["text"] = text
        return {"task_id": "tid", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    class FakeTask:
        status = "error"; note_id = None; error = "x"
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())
    rec = Recorder()
    await db.handle_message(111, "detailed notes from today", rec)
    assert seen["mode"] == "quick"
    assert seen["text"] == "detailed notes from today"  # 첫 단어 보존


@pytest.mark.asyncio
async def test_await_result_timeout(monkeypatch):
    """task가 계속 running이면 폴링 한도 후 timeout."""
    class Running:
        status = "running"; note_id = None; error = None
    monkeypatch.setattr(db, "get_task", lambda tid: Running())
    ticks = {"n": 0}
    async def fast_sleep(_):
        ticks["n"] += 1
    res = await db._await_result("tid", sleep=fast_sleep)
    assert res["status"] == "timeout"
    assert ticks["n"] == db._POLL_MAX_TICKS


@pytest.mark.asyncio
async def test_await_result_task_gone(monkeypatch):
    """task가 사라지면 error."""
    monkeypatch.setattr(db, "get_task", lambda tid: None)
    res = await db._await_result("tid")
    assert res["status"] == "error"
    assert "사라" in res["error"]
