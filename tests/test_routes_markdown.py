import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult


@pytest.mark.asyncio
async def test_markdown_quick_enqueues_and_saves_as_markdown_source_type():
    captured = {}
    async def fake_enqueue(task, fn): captured["fn"] = fn

    fake_ai = AsyncMock(); fake_ai.name.return_value = "claude"
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "문단"}], cost_usd=0.0, models_used=["m"])

    with patch("routers.markdown.enqueue", new=fake_enqueue), \
         patch("routers.markdown.get_provider", return_value=fake_ai), \
         patch("routers.markdown.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.markdown.record_api_cost", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/markdown",
                                data={"content": "# 제목\n\n본문 한 줄.",
                                      "provider": "claude", "mode": "quick"})
        assert resp.status_code == 200
        assert "task-" in resp.text
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)

    fake_ai.summarize.assert_awaited_once()
    summarize_args = fake_ai.summarize.call_args.args
    assert summarize_args[1] == "markdown"  # source_type 두 번째 위치 인자
    assert mock_save.call_args.kwargs["source_type"] == "markdown"
