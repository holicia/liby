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
    async def fake_count(db, provider):
        return 0
    async def fake_rows(db, limit=100):
        return [
            {"recorded_at": "2026-05-31 14:30:00", "provider": "claude",
             "model": "claude-sonnet-4-6", "cost_usd": 0.05,
             "item_id": 56, "note_title": "샘플 노트", "note_type": "youtube"},
        ]
    async def fake_daily(db, days=30):
        return [{"date": "2026-05-01", "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    async def fake_monthly_agg(db, months=12):
        return [{"month": "2026-05", "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    with patch("services.storage.get_monthly_cost", new=fake_monthly), \
         patch("services.storage.get_monthly_call_count", new=fake_count), \
         patch("services.storage.list_recent_api_costs", new=fake_rows), \
         patch("services.storage.aggregate_daily_costs", new=fake_daily), \
         patch("services.storage.aggregate_monthly_costs", new=fake_monthly_agg):
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
async def test_usage_report_renders_daily_and_monthly_charts():
    """/api/settings/usage가 일별/월별 차트 섹션을 렌더하고 다크모드 클래스 포함."""
    async def fake_monthly(db, provider):
        return 0.0
    async def fake_count(db, provider):
        return 0
    async def fake_rows(db, limit=100):
        return []
    async def fake_daily(db, days=30):
        return [
            {"date": f"2026-05-{i:02d}", "claude": 0.0, "gpt": 0.0,
             "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}
            for i in range(1, 31)
        ]
    async def fake_monthly_agg(db, months=12):
        return [
            {"month": f"2025-{i:02d}", "claude": 0.0, "gpt": 0.0,
             "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}
            for i in range(1, 13)
        ]
    with patch("services.storage.get_monthly_cost", new=fake_monthly), \
         patch("services.storage.get_monthly_call_count", new=fake_count), \
         patch("services.storage.list_recent_api_costs", new=fake_rows), \
         patch("services.storage.aggregate_daily_costs", new=fake_daily), \
         patch("services.storage.aggregate_monthly_costs", new=fake_monthly_agg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/usage")
    assert resp.status_code == 200
    assert "최근 30일 (일별)" in resp.text
    assert "최근 12개월 (월별)" in resp.text
    # 다크모드 적용
    assert "dark:bg-gray-900" in resp.text
    assert "dark:border-gray-700" in resp.text
    # 스택 색상
    assert "#8B5CF6" in resp.text
    assert "#22C55E" in resp.text


@pytest.mark.asyncio
async def test_usage_report_renders_four_provider_stacks():
    """/api/settings/usage가 4 provider 색상 모두 마크업에 포함."""
    async def fake_monthly_cost(db, provider): return 0.0
    async def fake_count(db, provider): return 5
    async def fake_rows(db, limit=100): return []
    async def fake_daily(db, days=30):
        return [{"date": "2026-06-01",
                 "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    async def fake_month(db, months=12):
        return [{"month": "2026-06",
                 "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    with patch("services.storage.get_monthly_cost", new=fake_monthly_cost), \
         patch("services.storage.get_monthly_call_count", new=fake_count), \
         patch("services.storage.list_recent_api_costs", new=fake_rows), \
         patch("services.storage.aggregate_daily_costs", new=fake_daily), \
         patch("services.storage.aggregate_monthly_costs", new=fake_month):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/usage")
    assert resp.status_code == 200
    assert "#8B5CF6" in resp.text  # claude
    assert "#22C55E" in resp.text  # gpt
    assert "#3B82F6" in resp.text  # claude-cli
    assert "#F97316" in resp.text  # codex-cli
    assert "Claude CLI" in resp.text
    assert "Codex CLI" in resp.text


@pytest.mark.asyncio
async def test_cost_widget_shows_cli_call_counts():
    """사이드바 위젯이 Claude CLI / Codex CLI 호출 횟수를 표시한다."""
    async def fake_monthly(db, provider):
        return {"claude": 0.0, "gpt": 0.0}.get(provider, 0.0)
    async def fake_count(db, provider):
        return {"claude-cli": 12, "codex-cli": 3}.get(provider, 0)
    with patch("services.storage.get_monthly_cost", new=fake_monthly), \
         patch("services.storage.get_monthly_call_count", new=fake_count):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/cost")
    assert resp.status_code == 200
    assert "Claude CLI" in resp.text
    assert "Codex CLI" in resp.text
    # 단순 "12"/"3"는 Tailwind 클래스(text-[10px], gap-3...)와 색상 hex에도 포함됨.
    # 템플릿의 `{{ count }}회` 패턴을 정확히 매칭.
    assert ">12회<" in resp.text
    assert ">3회<" in resp.text


@pytest.mark.asyncio
async def test_index_input_forms_offer_cli_providers():
    """5 input partial들이 claude-cli/codex-cli 옵션을 모두 노출해야 한다."""
    tabs = ["youtube", "pdf", "text", "code", "markdown"]
    claude_cli_count = 0
    codex_cli_count = 0
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # `/` includes youtube; the rest are htmx-loaded via /partials/input/{tab}.
        index = await c.get("/")
        assert index.status_code == 200
        claude_cli_count += index.text.count('value="claude-cli"')
        codex_cli_count += index.text.count('value="codex-cli"')
        for tab in tabs:
            resp = await c.get(f"/partials/input/{tab}")
            assert resp.status_code == 200, tab
            claude_cli_count += resp.text.count('value="claude-cli"')
            codex_cli_count += resp.text.count('value="codex-cli"')
    assert claude_cli_count >= 5
    assert codex_cli_count >= 5


@pytest.mark.asyncio
async def test_index_has_mobile_drawer():
    """메인 앱이 모바일 햄버거 토글 + 오프캔버스 드로어 + 오버레이를 갖춘다."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'id="sidebar-toggle"' in resp.text
    assert 'id="sidebar-overlay"' in resp.text
    assert "-translate-x-full" in resp.text
    assert "md:translate-x-0" in resp.text
    assert "function toggleSidebar" in resp.text
    assert "function closeSidebar" in resp.text


@pytest.mark.asyncio
async def test_index_has_analysis_toggle_and_collapsible_input():
    """모바일: + 분석 토글 + 접히는 입력 래퍼 + 탭 데스크톱 전용."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'id="analysis-toggle"' in resp.text
    assert 'id="analysis-panel"' in resp.text
    assert "function toggleAnalysis" in resp.text
    assert "hidden md:block" in resp.text
    assert "hidden md:flex items-stretch" in resp.text


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


@pytest.mark.asyncio
async def test_recommended_grid_single_col_mobile():
    """추천 노트 그리드가 모바일 1열·데스크톱 2열."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "grid-cols-1 md:grid-cols-2" in resp.text
