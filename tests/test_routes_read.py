import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app


YT_NOTE = {
    "id": 1, "type": "youtube", "title": "T", "summary": "요약",
    "tags": [], "topic": "", "summary_mode": "quick",
    "key_points": [], "paragraphs": [{"text": "본문", "refs": [{"t": 30, "snippet": "원문"}]}],
    "sections": [], "ai_provider": "claude", "api_cost_usd": 0.01,
    "created_at": "2026-05-31",
    "source_url": "https://youtu.be/dQw4w9WgXcY",
    "transcript_segments": [{"t": 0, "text": "안녕"}, {"t": 5, "text": "코끼리"}],
    "timeline": [{"t": 0, "label": "인트로"}],
    "insights": [], "questions_raised": [],
}


@pytest.mark.asyncio
async def test_read_view_renders_youtube_note():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=YT_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code == 200
    assert 'id="yt-player"' in resp.text
    assert "안녕" in resp.text and "코끼리" in resp.text
    assert "본문" in resp.text
    assert "ytSeek(30)" in resp.text


@pytest.mark.asyncio
async def test_read_view_redirects_non_youtube():
    pdf_note = {**YT_NOTE, "type": "pdf", "source_url": "paper.pdf"}
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=pdf_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code in (302, 307)
    assert resp.headers.get("location") == "/"


@pytest.mark.asyncio
async def test_read_view_redirects_when_note_missing():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/999/read")
    assert resp.status_code in (302, 307, 404)
