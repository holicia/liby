import json
import pytest
from unittest.mock import patch
from services.ai.fallback import FallbackProvider


@pytest.mark.asyncio
async def test_fallback_summarize_wires_paragraphs():
    provider = FallbackProvider()
    provider._cli_name, provider._cli_cmd = "claude", "claude"
    raw = json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "요약",
        "paragraphs": [
            {"text": "첫 문단", "refs": []},
            {"text": "둘째 문단", "refs": []},
        ],
        "tags": ["x"], "suggested_topic": "AI",
    }, ensure_ascii=False)
    with patch("services.ai.fallback._run_cli", return_value=raw):
        res = await provider.summarize("input", "youtube", "quick", [])
    assert res.paragraphs == [
        {"text": "첫 문단", "refs": []},
        {"text": "둘째 문단", "refs": []},
    ]
    assert res.summary_mode == "quick"
