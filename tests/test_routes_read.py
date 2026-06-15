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
async def test_read_view_renders_pdf_note_single_column():
    """PDF 논문 노트는 전체화면 read 뷰에서 단일 컬럼·인라인 그림으로 렌더(영상 없음)."""
    pdf_note = {
        **YT_NOTE, "type": "pdf", "source_url": "paper.pdf",
        "summary_mode": "detailed", "paragraphs": [],
        "sections": [
            {"heading": "4. 실험 결과", "subsections": [
                {"heading": "4.1 결과", "items": [
                    {"text": "보이드 저항 분석", "refs": [],
                     "image": {"file": "slug-abc/fig4.png", "caption": "Fig. 4. DC resistance"}},
                ]},
            ]},
        ],
    }
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=pdf_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code == 200
    assert 'id="yt-player"' not in resp.text          # 영상 플레이어 없음
    assert "/vault/pdf/slug-abc/fig4.png" in resp.text  # 인라인 그림
    assert "4. 실험 결과" in resp.text
    assert "max-w-3xl" in resp.text                    # 단일 컬럼 레이아웃


@pytest.mark.asyncio
async def test_read_view_redirects_when_note_missing():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/999/read")
    assert resp.status_code in (302, 307, 404)


@pytest.mark.asyncio
async def test_read_view_has_viewport_meta():
    """모바일 렌더링을 위해 read.html에 viewport 메타가 있어야 한다."""
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=YT_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code == 200
    assert 'name="viewport"' in resp.text
    assert "width=device-width" in resp.text


@pytest.mark.asyncio
async def test_read_view_mobile_reorder_container():
    """모바일 재배치용 flex/grid 컨테이너 + 트랜스크립트 order-3 적용."""
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=YT_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code == 200
    assert "flex flex-col md:grid" in resp.text
    assert "order-3" in resp.text            # 트랜스크립트가 모바일 맨 아래
    assert "안녕" in resp.text and "코끼리" in resp.text
