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


@pytest.mark.asyncio
async def test_get_projects_does_not_set_hx_trigger():
    # GET이 projectsChanged를 내보내면 사이드바가 재요청해 무한 루프가 된다
    with patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/projects")
    assert resp.status_code == 200
    assert "HX-Trigger" not in resp.headers


@pytest.mark.asyncio
async def test_mutations_set_hx_trigger():
    with patch("routers.projects.create_project", return_value=1), \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/projects", data={"name": "P"})
    assert resp.headers.get("HX-Trigger") == "projectsChanged"


@pytest.mark.asyncio
async def test_patch_project_renames():
    with patch("routers.projects.rename_project") as mock_rename, \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch("/api/projects/3", data={"name": "새 이름"})
    assert resp.status_code == 200
    mock_rename.assert_called_once()


@pytest.mark.asyncio
async def test_get_project_options_renders():
    with patch("routers.projects.list_projects", return_value=[{"id": 2, "name": "P2", "count": 0}]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/projects/options")
    assert resp.status_code == 200
    assert "P2" in resp.text
    assert "프로젝트 없음" in resp.text
