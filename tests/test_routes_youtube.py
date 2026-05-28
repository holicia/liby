import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.mark.asyncio
async def test_analyze_youtube_returns_task_card_fragment():
    # POST는 즉시 큐 작업 카드(task_card)를 반환하고 실제 분석은 워커가 비동기 처리.
    async def fake_enqueue(task, fn):
        return None
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/youtube", data={
                "url": "https://youtube.com/watch?v=abc123",
                "provider": "claude",
                "mode": "quick",
            })
    assert resp.status_code == 200
    assert "task-" in resp.text  # task_card 프래그먼트(id="task-...")

@pytest.mark.asyncio
async def test_analyze_youtube_missing_url_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/youtube", data={"provider": "claude", "mode": "quick"})
    assert resp.status_code == 422

@pytest.mark.asyncio
async def test_youtube_accepts_project_id():
    async def fake_enqueue(task, fn):
        return None
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/youtube", data={
                "url": "https://youtu.be/abc", "provider": "claude",
                "mode": "quick", "project_id": "7",
            })
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_youtube_do_work_generates_timeline():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn

    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=1, reading_time_min=1, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        cost_usd=0.0, models_used=["m"])
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": [{"t": 0, "label": "C"}], "segments": []}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([{"t": 0, "label": "C"}], 0.0, "")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc", "provider": "claude", "mode": "quick"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    assert mock_save.call_args.kwargs.get("timeline") == [{"t": 0, "label": "C"}]

@pytest.mark.asyncio
async def test_youtube_detailed_passes_timestamped_transcript():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="detailed",
        cost_usd=0.0, models_used=["m"])
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "PLAIN", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "안녕"}]}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1), \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc",
                                               "provider": "claude", "mode": "detailed"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    arg0 = fake_ai.summarize.call_args.args[0]
    assert "[0:00]" in arg0 and "안녕" in arg0  # 평문 PLAIN이 아니라 타임스탬프 자막 전달


@pytest.mark.asyncio
async def test_youtube_uses_video_title_for_queue_card():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["task"] = task
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider"), \
         patch("routers.youtube.youtube_title", new_callable=AsyncMock, return_value="My Video Title"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/youtube",
                data={"url": "https://youtu.be/abc", "provider": "claude", "mode": "quick"})
    assert resp.status_code == 200
    assert captured["task"].title == "My Video Title"


@pytest.mark.asyncio
async def test_youtube_falls_back_to_url_when_title_unavailable():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["task"] = task
    url = "https://youtu.be/xyz"
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider"), \
         patch("routers.youtube.youtube_title", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/youtube",
                data={"url": url, "provider": "claude", "mode": "quick"})
    assert resp.status_code == 200
    assert captured["task"].title == url
