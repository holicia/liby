import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult

MOCK_RESULT = SummaryResult(
    title="테스트 영상", language="ko", word_count=200,
    reading_time_min=2, sections=[],
    summary="요약 내용입니다.", key_points=["핵심1"],
    tags=["AI"], suggested_topic="AI/ML",
    summary_mode="quick", cost_usd=0.002,
    models_used=["claude-sonnet-4-6"],
)

@pytest.mark.asyncio
async def test_analyze_youtube_returns_htmx_fragment():
    with patch("routers.youtube.extract_youtube", return_value=("자막 텍스트", "abc123")), \
         patch("routers.youtube.get_provider") as mock_get, \
         patch("routers.youtube.save_note", return_value=1), \
         patch("routers.youtube.record_api_cost"):
        mock_provider = AsyncMock()
        mock_provider.name.return_value = "claude"
        mock_provider.summarize = AsyncMock(return_value=MOCK_RESULT)
        mock_get.return_value = mock_provider

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/youtube", data={
                "url": "https://youtube.com/watch?v=abc123",
                "provider": "claude",
                "mode": "quick",
            })
    assert resp.status_code == 200
    assert "테스트 영상" in resp.text

@pytest.mark.asyncio
async def test_analyze_youtube_missing_url_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/youtube", data={"provider": "claude", "mode": "quick"})
    assert resp.status_code == 422
