import pytest
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
