"""_parse_json 강건성: LLM(특히 CLI)이 JSON 앞뒤에 산문을 붙이거나
```json 펜스로 감싸도 본문 JSON 객체를 추출해야 한다."""
import pytest
from services.ai.claude import _parse_json


def test_pure_json():
    assert _parse_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_json_code_fence():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_bare_code_fence():
    assert _parse_json('```\n{"a": 1}\n```') == {"a": 1}


def test_trailing_prose_after_json():
    """실제 버그: claude CLI가 JSON 뒤에 설명을 덧붙임 → 'Extra data' 회귀 방지."""
    raw = '{"title": "t", "summary": "s"}\n\n요약: 타임스탬프가 없어 refs를 비웠습니다.'
    assert _parse_json(raw) == {"title": "t", "summary": "s"}


def test_leading_prose_before_json():
    raw = 'Here is the analysis:\n{"title": "t"}'
    assert _parse_json(raw) == {"title": "t"}


def test_prose_both_sides():
    raw = '분석 결과입니다:\n{"a": 1}\n도움이 되었길 바랍니다.'
    assert _parse_json(raw) == {"a": 1}


def test_braces_inside_string_values():
    """문자열 값 안의 중괄호·이스케이프가 객체 경계 탐지를 깨면 안 된다."""
    raw = '{"note": "use {curly} and \\"quoted\\" here", "n": 2} trailing'
    assert _parse_json(raw) == {"note": 'use {curly} and "quoted" here', "n": 2}


def test_fenced_json_with_trailing_prose():
    raw = '```json\n{"a": 1}\n```\n\n추가 설명입니다.'
    assert _parse_json(raw) == {"a": 1}


def test_nested_object():
    raw = 'prefix {"a": {"b": [1, 2]}, "c": 3} suffix'
    assert _parse_json(raw) == {"a": {"b": [1, 2]}, "c": 3}


def test_truly_invalid_raises():
    with pytest.raises((ValueError,)):
        _parse_json("이건 JSON이 전혀 아닙니다. 객체 없음.")
