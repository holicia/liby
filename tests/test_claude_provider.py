import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.ai.claude import ClaudeProvider

SAMPLE_TEXT = "LLM은 대규모 언어 모델이다. " * 20

@pytest.fixture
def provider():
    return ClaudeProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_summarize_quick_returns_paragraphs(provider):
    import json
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [],
        "summary": "한 줄 요약 2~3문장.",
        "paragraphs": [
            {"text": "첫 문단", "refs": [{"t": 12, "snippet": "원문 인용"}, {"t": 25, "snippet": "또 다른"}]},
            {"text": "두 번째 문단", "refs": []},
        ],
        "tags": ["x"], "suggested_topic": "AI/ML",
    }, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.summary == "한 줄 요약 2~3문장."
    assert res.paragraphs == [
        {"text": "첫 문단", "refs": [{"t": 12, "snippet": "원문 인용"}, {"t": 25, "snippet": "또 다른"}]},
        {"text": "두 번째 문단", "refs": []},
    ]
    assert res.summary_mode == "quick"

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
    assert result.insights is None

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


@pytest.mark.asyncio
async def test_generate_chapters_skips_non_numeric_t_and_sorts(provider):
    # LLM이 "0:00" 같은 비숫자 t를 섞어 보내거나 순서가 뒤섞여도 안전해야 함
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=
        '{"chapters": [{"t": "1:30", "label": "잘못"}, {"t": 90, "label": "뒤"}, {"t": 0, "label": "앞"}]}')]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        chapters, _, _ = await provider.generate_chapters("x")
    assert chapters == [{"t": 0, "label": "앞"}, {"t": 90, "label": "뒤"}]


@pytest.mark.asyncio
async def test_generate_chapters_handles_bad_json(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="죄송하지만 응답할 수 없습니다.")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        chapters, cost, model = await provider.generate_chapters("x")
    assert chapters == []
    assert cost > 0  # 호출 비용은 그대로 기록


def test_build_sections_hierarchy_and_timestamps():
    from services.ai.claude import _build_sections
    data = {"sections": [
        {"heading": "1. 대주제", "t": "0", "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "  문단 본문  ", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "두 번째"},
                {"text": "", "refs": [{"t": 5}]},  # text 없음 skip
            ]},
        ]},
    ]}
    assert _build_sections(data) == [
        {"heading": "1. 대주제", "t": 0, "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "문단 본문", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "두 번째", "refs": []},
            ]},
        ]},
    ]


def test_build_sections_skips_invalid():
    from services.ai.claude import _build_sections
    data = {"sections": ["notdict", {"heading": "", "subsections": []},
                         {"heading": "1. ok", "subsections": []}]}
    assert _build_sections(data) == [{"heading": "1. ok", "subsections": []}]


@pytest.mark.asyncio
async def test_summarize_detailed_builds_sections(provider):
    import json
    tier2 = MagicMock()
    tier2.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "summary": "한 줄 요약",
        "tags": ["x"], "suggested_topic": "AI",
        "sections": [{"heading": "1. A", "t": 0, "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "문단 2", "refs": []},
            ]}]}],
    }, ensure_ascii=False))]
    tier2.usage = MagicMock(input_tokens=10, output_tokens=10)
    tier3 = MagicMock()
    tier3.content = [MagicMock(text=json.dumps({"insights": ["i"], "questions_raised": ["q"]}))]
    tier3.usage = MagicMock(input_tokens=5, output_tokens=5)
    with patch.object(provider._client.messages, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("[0:00] hi", "youtube", "detailed", [])
    items = res.sections[0]["subsections"][0]["items"]
    assert items[0] == {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]}
    assert items[1] == {"text": "문단 2", "refs": []}
    assert res.insights == ["i"]


@pytest.mark.asyncio
async def test_translate_chapters(provider):
    import json
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(
        {"chapters": [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]}, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp):
        chapters, cost, model = await provider.translate_chapters(
            [{"t": 0, "label": "Intro"}, {"t": 90, "label": "Body"}])
    assert chapters == [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]
    assert cost > 0


@pytest.mark.asyncio
async def test_translate_chapters_empty_returns_empty(provider):
    chapters, cost, model = await provider.translate_chapters([])
    assert chapters == [] and cost == 0.0


def test_build_paragraphs_keeps_text_and_refs():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        {"text": "  문단 1  ", "refs": [{"t": "30", "snippet": "원문"}, {"t": 60}]},
        {"text": "문단 2"},  # refs 없음
    ]}
    assert _build_paragraphs(data) == [
        {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}, {"t": 60}]},
        {"text": "문단 2", "refs": []},
    ]


def test_build_paragraphs_skips_invalid():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        "notdict",
        {"text": ""},
        {"refs": [{"t": 5}]},  # text 없음 → skip
        {"text": "ok"},  # refs 없으면 빈 list
    ]}
    assert _build_paragraphs(data) == [{"text": "ok", "refs": []}]


def test_build_refs_keeps_t_and_snippet():
    from services.ai.claude import _build_refs
    data = [
        {"t": "30", "snippet": "  원문  "},
        {"t": 90},
    ]
    assert _build_refs(data) == [
        {"t": 30, "snippet": "원문"},
        {"t": 90},
    ]


def test_build_refs_skips_invalid():
    from services.ai.claude import _build_refs
    data = [
        "notdict",
        {"snippet": "no t"},
        {"t": "1:30", "snippet": "non-numeric t"},
        {"t": 5, "snippet": ""},
    ]
    assert _build_refs(data) == [{"t": 5}]


def test_build_refs_empty_input():
    from services.ai.claude import _build_refs
    assert _build_refs([]) == []
