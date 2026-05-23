import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.ai.openai_provider import OpenAIProvider

SAMPLE_TEXT = "GPT는 생성형 AI 모델이다. " * 20

@pytest.fixture
def provider():
    return OpenAIProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_summarize_quick_returns_result(provider):
    mock_choice = MagicMock()
    mock_choice.message.content = """
{
  "title": "GPT 개요", "language": "ko", "word_count": 50,
  "reading_time_min": 1, "sections": [],
  "summary": "GPT는 생성형 AI이다.",
  "key_points": ["포인트1"],
  "tags": ["AI"],
  "suggested_topic": "AI/ML"
}
"""
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_resp.model = "gpt-4o"

    with patch.object(provider._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_resp):
        result = await provider.summarize(SAMPLE_TEXT, "pdf", "quick", [])

    assert result.title == "GPT 개요"
    assert result.summary_mode == "quick"
    assert result.cost_usd > 0

def test_provider_name(provider):
    assert provider.name() == "gpt"
