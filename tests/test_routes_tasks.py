"""tasks 라우터: 에러 카드 닫기(dismiss) 동작 검증."""
import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from services import task_queue as tq


@pytest.fixture(autouse=True)
def _reset():
    tq._reset_for_tests()
    yield
    tq._reset_for_tests()


@pytest.mark.asyncio
async def test_error_card_has_dismiss_button():
    """error 상태 task의 카드에 닫기(dismiss) 버튼이 있어야 한다."""
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    task.status = "error"
    task.error = "분석 중 오류"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/tasks/{task.id}")
    assert resp.status_code == 200
    assert f"/api/tasks/{task.id}/dismiss" in resp.text
    assert "분석 중 오류" in resp.text


@pytest.mark.asyncio
async def test_dismiss_removes_error_card():
    """dismiss POST는 빈 응답으로 카드를 제거하고 task를 정리한다."""
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    task.status = "error"
    task.error = "boom"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/tasks/{task.id}/dismiss")
    assert resp.status_code == 200
    assert resp.text == ""
    assert task.id not in tq._tasks


@pytest.mark.asyncio
async def test_dismiss_running_task_conflict():
    """진행 중 task는 dismiss 불가(409)."""
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    task.status = "running"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/tasks/{task.id}/dismiss")
    assert resp.status_code == 409
