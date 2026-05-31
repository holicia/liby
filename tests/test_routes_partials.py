import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_pdf_input_partial_uses_label_wrapped_input():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/partials/input/pdf")
    assert resp.status_code == 200
    # input은 hidden, label이 전체 클릭 영역
    assert '<label' in resp.text
    assert 'class="hidden"' in resp.text
    assert 'pdf-filename' in resp.text
    assert 'hx-post="/api/pdf"' in resp.text


@pytest.mark.asyncio
async def test_api_cost_partial_uses_new_header_text():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/settings/cost")
    assert resp.status_code == 200
    assert "API 사용 현황" in resp.text
    assert "이번 달 API" not in resp.text


@pytest.mark.asyncio
async def test_index_cost_widget_listens_to_note_completed_event():
    """sidebar 비용 위젯이 task 완료 이벤트(noteCompleted)에도 자동 갱신되어야 한다."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "noteCompleted from:body" in resp.text
    assert "every 60s" in resp.text  # 폴링 백업 유지


@pytest.mark.asyncio
async def test_index_theme_toggle_uses_icon():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    # 토글 버튼 자체 + 초기 아이콘 (라이트 모드 시작 → 다음으로 갈 다크의 아이콘 🌙)
    assert 'id="theme-btn"' in resp.text
    assert '🌙' in resp.text
    assert '다크 모드' not in resp.text
    assert '라이트 모드' not in resp.text


@pytest.mark.asyncio
async def test_cost_widget_has_usage_detail_link():
    """sidebar 위젯의 '상세' 텍스트가 /api/settings/usage로 가는 링크여야 한다."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/settings/cost")
    assert resp.status_code == 200
    assert 'href="/api/settings/usage"' in resp.text


@pytest.mark.asyncio
async def test_usage_report_renders_with_recent_calls():
    """/api/settings/usage가 누적 카드 + 최근 호출 표를 렌더."""
    async def fake_monthly(db, provider):
        return 0.42 if provider == "claude" else 0.0
    async def fake_rows(db, limit=100):
        return [
            {"recorded_at": "2026-05-31 14:30:00", "provider": "claude",
             "model": "claude-sonnet-4-6", "cost_usd": 0.05,
             "item_id": 56, "note_title": "샘플 노트", "note_type": "youtube"},
        ]
    with patch("services.storage.get_monthly_cost", new=fake_monthly), \
         patch("services.storage.list_recent_api_costs", new=fake_rows):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/usage")
    assert resp.status_code == 200
    assert "샘플 노트" in resp.text
    assert "claude-sonnet-4-6" in resp.text
    assert "0.0500" in resp.text  # %.4f
    assert "0.42" in resp.text     # 누적 %.2f
    # KST 변환된 일시 표시 (UTC 14:30 → KST 23:30)
    assert "2026-05-31 23:30" in resp.text


@pytest.mark.asyncio
async def test_vault_static_mount_serves_existing_file(tmp_path):
    """/vault/<path>가 config.VAULT_PATH 하위의 실제 파일을 서빙해야 한다."""
    import config
    import pathlib
    target_dir = pathlib.Path(config.VAULT_PATH) / "youtube" / "_test_static_mount"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "ch-1.txt"
    target.write_text("hello", encoding="utf-8")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/vault/youtube/_test_static_mount/ch-1.txt")
        assert resp.status_code == 200
        assert resp.text == "hello"
    finally:
        target.unlink(missing_ok=True)
        try: target_dir.rmdir()
        except OSError: pass
