import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_get_projects_renders_list():
    with patch("routers.projects.list_projects", return_value=[{"id": 1, "name": "회사 리서치", "count": 2}]), \
         patch("routers.projects.unassigned_count", return_value=3):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/projects")
    assert resp.status_code == 200
    assert "회사 리서치" in resp.text
    assert "미분류" in resp.text


@pytest.mark.asyncio
async def test_post_project_creates():
    with patch("routers.projects.create_project", return_value=1) as mock_create, \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/projects", data={"name": "새 프로젝트"})
    assert resp.status_code == 200
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_delete_project():
    with patch("routers.projects.delete_project") as mock_del, \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/projects/5")
    assert resp.status_code == 200
    mock_del.assert_called_once()
