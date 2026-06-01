import pytest
from unittest.mock import AsyncMock, patch
import config


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


def test_bridge_provider_init_requires_valid_adapter():
    from services.ai.bridge import BridgeProvider
    BridgeProvider(adapter="claude")  # ok
    BridgeProvider(adapter="codex")   # ok
    with pytest.raises(ValueError, match="adapter"):
        BridgeProvider(adapter="invalid")


def test_bridge_provider_name_reflects_adapter():
    from services.ai.bridge import BridgeProvider
    assert BridgeProvider(adapter="claude").name() == "claude-cli"
    assert BridgeProvider(adapter="codex").name() == "codex-cli"


def test_bridge_provider_missing_token_raises(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "")
    from services.ai.bridge import BridgeProvider
    with pytest.raises(RuntimeError, match="BRIDGE_TOKEN"):
        BridgeProvider(adapter="claude")


@pytest.mark.asyncio
async def test_bridge_summarize_short_text_single_run(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    fake = AsyncMock(return_value=bc.BridgeRunResult(
        summary=(
            '{"title":"제목","language":"ko","word_count":10,'
            '"reading_time_min":1,"sections":[],'
            '"summary":"요약","paragraphs":[{"text":"문단1","refs":[]}],'
            '"tags":["t1"],"suggested_topic":"주제"}'
        ),
        session_id="s1",
        usage=bc.BridgeUsage(input_tokens=200, output_tokens=80, total_cost_usd=0.0),
    ))
    monkeypatch.setattr(bc, "run_agent", fake)

    p = BridgeProvider(adapter="claude")
    result = await p.summarize("짧은 텍스트", "youtube", "quick", [])

    assert result.title == "제목"
    assert result.summary == "요약"
    assert result.paragraphs == [{"text": "문단1", "refs": []}]
    assert result.cost_usd == 0.0
    assert result.models_used == ["claude"]
    fake.assert_awaited_once()
    kwargs = fake.await_args.kwargs
    assert kwargs["adapter"] == "claude"


@pytest.mark.asyncio
async def test_bridge_summarize_long_text_triggers_chunking(monkeypatch):
    """CHUNK_THRESHOLD 초과 시 chunk 수 + 1(merge) 호출."""
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc, chunking
    long_text = ("줄\n" * 10000)  # > 18000자
    assert len(long_text) > chunking.CHUNK_THRESHOLD

    def stub_summary(i: int) -> str:
        return (
            f'{{"title":"t{i}","language":"ko","word_count":1,'
            f'"reading_time_min":1,"sections":[],'
            f'"summary":"부분요약 {i}","paragraphs":[],'
            f'"tags":[],"suggested_topic":""}}'
        )

    call_count = {"n": 0}
    async def fake(prompt, **kw):
        call_count["n"] += 1
        i = call_count["n"]
        if "[조각 1]" in prompt:  # merge
            return bc.BridgeRunResult(
                summary='{"summary":"통합 요약"}', session_id=None,
                usage=bc.BridgeUsage())
        return bc.BridgeRunResult(
            summary=stub_summary(i), session_id=None,
            usage=bc.BridgeUsage(input_tokens=10, output_tokens=10))

    monkeypatch.setattr(bc, "run_agent", fake)
    p = BridgeProvider(adapter="claude")
    result = await p.summarize(long_text, "youtube", "quick", [])
    chunks = chunking.chunk_for_llm(long_text)
    assert call_count["n"] == len(chunks) + 1  # partials + merge
    assert result.summary == "통합 요약"


@pytest.mark.asyncio
async def test_bridge_generate_chapters_calls_run_agent(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary='{"chapters":[{"t":0,"label":"intro"},{"t":120,"label":"part1"}]}',
        session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    chapters, cost, model = await p.generate_chapters("자막 텍스트")
    assert chapters == [{"t": 0, "label": "intro"}, {"t": 120, "label": "part1"}]
    assert cost == 0.0
    assert model == "claude"


@pytest.mark.asyncio
async def test_bridge_generate_chapters_bad_json_returns_empty(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary="잘못된 응답", session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    chapters, _, _ = await p.generate_chapters("자막")
    assert chapters == []


@pytest.mark.asyncio
async def test_bridge_translate_chapters_empty_input_returns_empty(monkeypatch):
    from services.ai.bridge import BridgeProvider
    p = BridgeProvider(adapter="claude")
    out, cost, model = await p.translate_chapters([])
    assert out == []
    assert cost == 0.0


@pytest.mark.asyncio
async def test_bridge_translate_chapters_translates(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary='{"chapters":[{"t":0,"label":"소개"}]}',
        session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    out, _, _ = await p.translate_chapters([{"t": 0, "label": "intro"}])
    assert out == [{"t": 0, "label": "소개"}]


@pytest.mark.asyncio
async def test_bridge_translate_chapters_failure_returns_original(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary="잘못된 응답", session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    original = [{"t": 0, "label": "intro"}]
    out, _, _ = await p.translate_chapters(original)
    assert out == original
