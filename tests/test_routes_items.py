import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
import config
from main import app

MOCK_NOTE = {
    "id": 1, "type": "youtube", "title": "테스트", "summary": "요약",
    "tags": '["AI"]', "topic": "AI/ML", "summary_mode": "quick",
    "key_points": '["핵심1"]', "ai_provider": "claude",
    "api_cost_usd": 0.003, "created_at": "2026-05-23",
    "source_url": "https://youtube.com/watch?v=abc",
}


@pytest.mark.asyncio
async def test_card_displays_api_cost_usd_value():
    """노트 카드 비용 표시가 api_cost_usd 값을 반영(0.000이 아닌 실제 값)."""
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items")
    assert resp.status_code == 200
    assert "$0.003" in resp.text
    assert "$0.000" not in resp.text

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
    # 상세 정리는 즉시 task_card를 반환하고 실제 작업은 큐에서 비동기 처리.
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE), \
         patch("routers.items.get_provider", return_value=AsyncMock()), \
         patch("routers.items.enqueue", new=fake_enqueue), \
         patch("routers.items.upgrade_to_detailed", new_callable=AsyncMock) as mock_upgrade, \
         patch("routers.items.record_api_cost", new_callable=AsyncMock), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": [{"t": 0, "label": "C"}], "segments": []}), \
         patch("routers.items.resolve_chapters", new_callable=AsyncMock, return_value=([{"t": 0, "label": "C"}], 0.0, "")), \
         patch("routers.items.set_timeline", new_callable=AsyncMock) as mock_set:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/items/1/upgrade")
        assert resp.status_code == 200
        assert "task-" in resp.text  # task_card 프래그먼트 반환
        # 큐에 들어간 do_work를 직접 실행
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    mock_upgrade.assert_awaited_once()
    mock_set.assert_awaited_once()  # MOCK_NOTE는 youtube → 타임라인도 생성


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
    with patch("routers.items.set_note_project", new_callable=AsyncMock) as mock_set, \
         patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE), \
         patch("routers.items.list_projects", new_callable=AsyncMock, return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/project", data={"project_id": "5"})
    assert resp.status_code == 200
    mock_set.assert_awaited_once_with(config.DB_PATH, 1, 5)


@pytest.mark.asyncio
async def test_detail_passes_video_id_for_youtube():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert MOCK_NOTE["title"] in resp.text


@pytest.mark.asyncio
async def test_detail_renders_legacy_lead_bullets_items():
    """옛 {lead, bullets} 형태 detailed 노트가 모달에서 폴백 분기로 정상 렌더되는지."""
    legacy = dict(MOCK_NOTE)
    legacy.update({
        "summary_mode": "detailed",
        "sections": [{"heading": "1. 대주제", "subsections": [
            {"heading": "1.1 소주제", "items": [
                {"lead": "옛 핵심 한 줄", "bullets": ["옛 불릿 A", "옛 불릿 B"]},
            ]},
        ]}],
        "paragraphs": [],  # 옛 노트는 paragraphs 없음
    })
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=legacy):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "옛 핵심 한 줄" in resp.text
    assert "옛 불릿 A" in resp.text
    assert "옛 불릿 B" in resp.text


@pytest.mark.asyncio
async def test_detail_renders_legacy_quick_key_points_fallback():
    """옛 quick 노트(paragraphs 없고 key_points만 있음)가 핵심 포인트 폴백으로 렌더되는지."""
    legacy = dict(MOCK_NOTE)
    legacy.update({
        "summary_mode": "quick", "sections": [],
        "key_points": ["옛 핵심 1", "옛 핵심 2"], "paragraphs": [],
    })
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=legacy):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "핵심 포인트" in resp.text
    assert "옛 핵심 1" in resp.text
    assert "옛 핵심 2" in resp.text


@pytest.mark.asyncio
async def test_backfill_timeline_calls_set_timeline():
    note = dict(MOCK_NOTE)
    fake_ai = MagicMock()
    fake_ai.name.return_value = "claude"
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None, "segments": [{"t": 0, "text": "a"}]}), \
         patch("routers.items.get_provider", return_value=fake_ai), \
         patch("routers.items.resolve_chapters", new_callable=AsyncMock, return_value=([{"t": 0, "label": "C"}], 0.0, "")), \
         patch("routers.items.set_timeline", new_callable=AsyncMock) as mock_set, \
         patch("routers.items.record_api_cost", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/timeline")
    assert resp.status_code == 200
    mock_set.assert_awaited_once_with(config.DB_PATH, 1, [{"t": 0, "label": "C"}])


@pytest.mark.asyncio
async def test_backfill_timeline_skips_non_youtube():
    pdf_note = {**MOCK_NOTE, "type": "pdf", "source_url": "paper.pdf"}
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=pdf_note), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock) as mock_extract, \
         patch("routers.items.set_timeline", new_callable=AsyncMock) as mock_set:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/timeline")
    assert resp.status_code == 200
    mock_extract.assert_not_called()  # 비-youtube는 추출 시도 안 함
    mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_upgrade_youtube_regenerates_sections():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    note = {**MOCK_NOTE, "type": "youtube", "source_url": "https://youtu.be/abc", "summary": "s"}
    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    full = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": []}],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="detailed",
        insights=["i"], questions_raised=["q"], cost_usd=0.0, models_used=["m"])
    fake_ai.summarize.return_value = full
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note), \
         patch("routers.items.get_provider", return_value=fake_ai), \
         patch("routers.items.enqueue", new=fake_enqueue), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "a"}]}), \
         patch("routers.items.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")), \
         patch("routers.items.set_timeline", new_callable=AsyncMock), \
         patch("routers.items.upgrade_to_detailed", new_callable=AsyncMock) as mock_up, \
         patch("routers.items.record_api_cost", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/upgrade")
        assert resp.status_code == 200
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    passed = mock_up.call_args.args[2]  # upgrade_to_detailed(db_path, note_id, result)
    assert passed.sections[0]["heading"] == "1. A"
    fake_ai.summarize.assert_awaited_once()


@pytest.mark.asyncio
async def test_upgrade_non_youtube_uses_run_tier3():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    note = {**MOCK_NOTE, "type": "pdf", "source_url": "paper.pdf", "summary": "s"}
    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    detailed = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="detailed",
        insights=["i"], questions_raised=["q"], cost_usd=0.0)
    fake_ai.run_tier3.return_value = detailed
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note), \
         patch("routers.items.get_provider", return_value=fake_ai), \
         patch("routers.items.enqueue", new=fake_enqueue), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock) as mock_extract, \
         patch("routers.items.upgrade_to_detailed", new_callable=AsyncMock), \
         patch("routers.items.record_api_cost", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/upgrade")
        assert resp.status_code == 200
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    fake_ai.run_tier3.assert_awaited_once()
    fake_ai.summarize.assert_not_called()  # 비youtube는 요약 재실행 안 함
    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_delete_item_removes_db_row_and_file(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("body", encoding="utf-8")
    async def fake_delete_note(db, nid):
        assert nid == 1
        return str(md)
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/1")
    assert resp.status_code == 200
    assert resp.text == ""
    assert not md.exists()


@pytest.mark.asyncio
async def test_delete_item_is_idempotent_when_row_missing(tmp_path):
    async def fake_delete_note(db, nid): return None
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/999")
    assert resp.status_code == 200
    assert resp.text == ""


@pytest.mark.asyncio
async def test_delete_item_swallows_missing_file(tmp_path):
    missing = tmp_path / "gone.md"
    async def fake_delete_note(db, nid): return str(missing)
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/1")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_card_renders_delete_button():
    """카드에 hx-delete 휴지통 버튼이 렌더돼야 한다."""
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items")
    assert resp.status_code == 200
    assert 'hx-delete="/api/items/1"' in resp.text
    assert 'id="note-card-1"' in resp.text
    assert 'hx-target="#note-card-1"' in resp.text


@pytest.mark.asyncio
async def test_modal_renders_delete_button():
    """모달 우상단에 hx-delete 휴지통이 렌더돼야 한다."""
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert 'hx-delete="/api/items/1"' in resp.text
    assert 'closeNoteModal()' in resp.text
    assert 'hx-confirm=' in resp.text
    assert 'hx-swap="outerHTML"' in resp.text


@pytest.mark.asyncio
async def test_modal_renders_screenshot_toggle_when_timeline_has_images():
    """timeline에 image 키가 있으면 모달이 토글 + img 마크업을 렌더."""
    note = dict(MOCK_NOTE)
    note["source_url"] = "https://youtube.com/watch?v=dQw4w9WgXcY"  # 11-char video ID
    note["timeline"] = [
        {"t": 0, "label": "A", "image": "slug/ch-1.jpg"},
        {"t": 90, "label": "B", "image": "slug/ch-2.jpg"},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "📷 스크린샷 보기" in resp.text
    assert 'src="/vault/youtube/slug/ch-1.jpg"' in resp.text
    assert 'src="/vault/youtube/slug/ch-2.jpg"' in resp.text


@pytest.mark.asyncio
async def test_modal_hides_screenshot_toggle_when_no_images():
    """timeline에 image 키가 없으면 토글 마크업이 안 보여야 한다."""
    note = dict(MOCK_NOTE)
    note["source_url"] = "https://youtube.com/watch?v=dQw4w9WgXcY"  # 11-char video ID
    note["timeline"] = [
        {"t": 0, "label": "A"},
        {"t": 90, "label": "B"},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "📷 스크린샷 보기" not in resp.text
