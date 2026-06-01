def test_chunking_exports_helpers_for_bridge_provider():
    """bridge provider가 필요로 하는 모든 헬퍼가 chunking에서 import 가능해야 한다."""
    from services.ai import chunking
    # transport-무관 유틸리티
    assert callable(chunking.chunk_for_llm)
    assert callable(chunking.chunk_range_hint)
    assert callable(chunking.extract_json)
    assert callable(chunking.build_paragraphs)
    assert callable(chunking.build_sections)
    assert callable(chunking.build_chapters)
    assert callable(chunking.build_refs)
    assert callable(chunking.renumber_sections)
    assert callable(chunking.to_t)
    # 상수
    assert chunking.CHUNK_THRESHOLD == 18000
    assert "조각" in chunking.SUMMARY_MERGE_PROMPT


def test_chunking_chunk_for_llm_short_text_returns_single_chunk():
    from services.ai.chunking import chunk_for_llm
    text = "한 줄짜리\n짧은 텍스트"
    assert chunk_for_llm(text) == [text]


def test_chunking_extract_json_strips_code_fence():
    from services.ai.chunking import extract_json
    raw = '```json\n{"title": "Test"}\n```'
    assert extract_json(raw) == {"title": "Test"}
