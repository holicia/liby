import json
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

@pytest.mark.asyncio
async def test_openai_summarize_detailed_builds_sections(provider):
    import json
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "summary": "요약",
        "tags": [], "suggested_topic": "",
        "sections": [{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "문단 2", "refs": []},
            ]}]}],
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    tier3 = MagicMock()
    tier3.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "insights": ["i"], "questions_raised": ["q"],
    })))]
    tier3.usage = MagicMock(prompt_tokens=5, completion_tokens=5)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("input", "youtube", "detailed", [])
    items = res.sections[0]["subsections"][0]["items"]
    assert items[0] == {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]}
    assert items[1] == {"text": "문단 2", "refs": []}


@pytest.mark.asyncio
async def test_openai_quick_returns_paragraphs(provider):
    import json
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "요약",
        "paragraphs": [{"text": "문단", "refs": [{"t": 30, "snippet": "원문"}]}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, return_value=tier2):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.paragraphs == [{"text": "문단", "refs": [{"t": 30, "snippet": "원문"}]}]
