import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app

MOCK_NOTE = {
    "id": 1, "type": "youtube", "title": "테스트", "summary": "요약",
    "tags": '["AI"]', "topic": "AI/ML", "summary_mode": "quick",
    "key_points": '["핵심1"]', "ai_provider": "claude",
    "cost_usd": 0.003, "created_at": "2026-05-23",
    "source_url": "https://youtube.com/watch?v=abc",
}

@pytest.mark.asyncio
async def test_get_items_returns_list():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/items")
    assert resp.status_code == 200
    assert "테스트" in resp.text

@pytest.mark.asyncio
async def test_get_items_with_tag_filter():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/items?tags=AI&tags=LLM")
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_upgrade_to_detailed():
    from services.ai.base import SummaryResult
    detailed_result = SummaryResult(
        title="테스트", language="ko", word_count=100,
        reading_time_min=1, sections=[],
        summary="요약", key_points=["핵심1"],
        tags=["AI"], suggested_topic="AI/ML",
        summary_mode="detailed", cost_usd=0.01,
        models_used=["claude-opus-4-7"],
        main_arguments=["논거1"],
        insights=["인사이트1"],
        questions_raised=["질문1"],
        related_concepts=["개념1"],
    )
    with patch("routers.items.get_note", return_value=MOCK_NOTE), \
         patch("routers.items.get_provider") as mock_get, \
         patch("routers.items.upgrade_to_detailed", return_value=detailed_result), \
         patch("routers.items.record_api_cost"), \
         patch("routers.items.list_projects", return_value=[]):
        mock_get.return_value = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/items/1/upgrade")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_items_with_project_filter():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]) as mock_list, \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items?project_id=3")
    assert resp.status_code == 200
    assert mock_list.call_args.kwargs.get("project_id") == "3"


@pytest.mark.asyncio
async def test_set_note_project():
    with patch("routers.items.set_note_project") as mock_set, \
         patch("routers.items.get_note", return_value=MOCK_NOTE), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/project", data={"project_id": "5"})
    assert resp.status_code == 200
    mock_set.assert_called_once()
    assert mock_set.call_args.args[2] == 5
