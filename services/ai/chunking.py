"""Transport-무관 분석 헬퍼.

bridge·claude·openai_provider 등 모든 AIProvider 구현체가 공유한다.
원본 함수들은 historical reason으로 services.extractor와 services.ai.claude에
흩어져 있어, 여기서 깔끔한 이름으로 re-export한다.
"""
from services.extractor import _chunk_for_llm as chunk_for_llm
from services.extractor import _chunk_range_hint as chunk_range_hint
from services.ai.claude import (
    _parse_json as extract_json,
    _build_paragraphs as build_paragraphs,
    _build_sections as build_sections,
    _build_chapters as build_chapters,
    _build_refs as build_refs,
    _renumber_sections as renumber_sections,
    _to_t as to_t,
    SUMMARY_MERGE_PROMPT,
    CHUNK_THRESHOLD,
)

__all__ = [
    "chunk_for_llm", "chunk_range_hint", "extract_json",
    "build_paragraphs", "build_sections", "build_chapters",
    "build_refs", "renumber_sections", "to_t",
    "SUMMARY_MERGE_PROMPT", "CHUNK_THRESHOLD",
]
