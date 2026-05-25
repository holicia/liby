import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.ai.claude import ClaudeProvider

SAMPLE_TEXT = "LLM은 대규모 언어 모델이다. " * 20

@pytest.fixture
def provider():
    return ClaudeProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_summarize_quick_returns_summary_result(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{
  "title": "LLM 개요",
  "language": "ko",
  "word_count": 100,
  "reading_time_min": 1,
  "sections": [],
  "summary": "LLM은 대규모 언어 모델이다.",
  "key_points": ["핵심1", "핵심2"],
  "tags": ["AI", "LLM"],
  "suggested_topic": "AI/ML"
}
""")]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        result = await provider.summarize(SAMPLE_TEXT, "youtube", "quick", ["AI/ML"])

    assert result.title == "LLM 개요"
    assert result.summary_mode == "quick"
    assert result.main_arguments is None
    assert result.cost_usd > 0

@pytest.mark.asyncio
async def test_summarize_quick_mode_skips_tier3(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{
  "title": "T", "language": "ko", "word_count": 10,
  "reading_time_min": 1, "sections": [],
  "summary": "요약", "key_points": ["p1"],
  "tags": ["tag"], "suggested_topic": "주제"
}
""")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=10)

    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response) as mock_create:
        result = await provider.summarize(SAMPLE_TEXT, "pdf", "quick", [])

    # quick 모드에서는 Tier2까지만 → create 호출 1회
    assert mock_create.call_count == 1
    assert result.main_arguments is None

def test_provider_name(provider):
    assert provider.name() == "claude"

@pytest.mark.asyncio
async def test_generate_chapters_parses_json(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{"chapters": [{"t": 0, "label": "인트로"}, {"t": 150, "label": "핵심 개념"}]}
""")]
    mock_response.usage = MagicMock(input_tokens=200, output_tokens=80)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        chapters, cost, model = await provider.generate_chapters("[0:00] 안녕\n[2:30] 개념")
    assert chapters == [{"t": 0, "label": "인트로"}, {"t": 150, "label": "핵심 개념"}]
    assert cost > 0
    assert model
