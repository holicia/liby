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
async def test_project_row_uses_data_attributes_not_inline_tojson_in_onclick():
    """프로젝트 row click handler가 한국어 이름 때문에 onclick attribute 안의
    inner quote로 잘리지 않게 data-* 패턴을 써야 한다. tojson 호출이 onclick
    안에 들어가 있던 옛 패턴은 한국어 이름에서 attribute가 깨졌었다."""
    with patch("routers.projects.list_projects", return_value=[
              {"id": 2, "name": "투자", "count": 6}]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/projects")
    assert resp.status_code == 200
    # data 속성으로 id/name 전달
    assert 'data-project-id="2"' in resp.text
    assert 'data-project-name="투자"' in resp.text
    # enterProjectView 호출은 dataset을 통해
    assert "enterProjectView(this.dataset.projectId, this.dataset.projectName)" in resp.text
    # 옛 깨지는 패턴(tojson을 onclick 인자에 직접 박는 것)이 다시 들어오지 않도록
    assert 'enterProjectView(2, "투자"' not in resp.text
    assert 'enterProjectView(2, "\\u' not in resp.text


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
