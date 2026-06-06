"""provider=claude-cli로 요청해도 라우터가 BridgeProvider를 받는지 검증."""
import pytest
import config
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


@pytest.mark.asyncio
async def test_text_route_accepts_claude_cli_provider():
    """POST /api/text 가 provider=claude-cli를 받아 spec을 만들고 enqueue한다.
    builder로 재구성한 do_work가 BridgeProvider.summarize를 호출하는지 확인."""
    import routers.text as text_mod
    fake_summarize = AsyncMock(return_value=SummaryResult(
        title="t", language="ko", word_count=1, reading_time_min=1,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "x", "refs": []}],
        cost_usd=0.0, models_used=["claude"],
    ))
    captured = {}
    async def fake_enqueue(task, coro_fn=None):
        captured["task"] = task

    with patch("services.ai.bridge.BridgeProvider.summarize", new=fake_summarize), \
         patch("routers.text.enqueue", new=fake_enqueue), \
         patch("routers.text.save_note", new_callable=AsyncMock, return_value=1), \
         patch("routers.text.record_api_cost", new_callable=AsyncMock), \
         patch("routers.text.get_db_topics") as mock_topics:
        mock_topics.return_value.__aenter__.return_value = []
        mock_topics.return_value.__aexit__.return_value = False
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/text", data={
                "content": "안녕하세요. 짧은 입력 텍스트입니다.",
                "provider": "claude-cli", "mode": "quick",
            })
        assert resp.status_code == 200
        # spec으로 do_work 재구성 후 직접 실행 → summarize 호출됨
        task = captured["task"]
        assert task.spec["provider"] == "claude-cli"
        do_work = text_mod._build_text_do_work(task.spec)
        t = MagicMock(); t.note_id = None
        await do_work(t)
    fake_summarize.assert_awaited()
