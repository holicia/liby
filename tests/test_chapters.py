import pytest
from unittest.mock import AsyncMock
from services.chapters import resolve_chapters


@pytest.mark.asyncio
async def test_resolve_uses_native_when_present():
    ai = AsyncMock()
    native = [{"t": 0, "label": "인트로"}]
    chapters, cost, model = await resolve_chapters(native, [{"t": 0, "text": "x"}], ai)
    assert chapters == native
    assert cost == 0.0
    assert model == ""
    ai.generate_chapters.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_falls_back_to_ai():
    ai = AsyncMock()
    ai.generate_chapters.return_value = ([{"t": 0, "label": "AI"}], 0.01, "claude-sonnet-4-6")
    chapters, cost, model = await resolve_chapters(None, [{"t": 0, "text": "안녕"}], ai)
    assert chapters == [{"t": 0, "label": "AI"}]
    assert cost == 0.01
    assert model == "claude-sonnet-4-6"
    ai.generate_chapters.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_no_segments_returns_empty():
    ai = AsyncMock()
    chapters, cost, model = await resolve_chapters(None, [], ai)
    assert chapters == []
    assert cost == 0.0
    assert model == ""
    ai.generate_chapters.assert_not_called()


def test_labels_are_korean():
    from services.chapters import _labels_are_korean
    assert _labels_are_korean([{"t": 0, "label": "인트로"}]) is True
    assert _labels_are_korean([{"t": 0, "label": "Intro"}]) is False
    assert _labels_are_korean([{"t": 0, "label": "Intro 도입"}]) is True


@pytest.mark.asyncio
async def test_resolve_keeps_korean_native():
    ai = AsyncMock()
    native = [{"t": 0, "label": "인트로"}]
    chapters, cost, model = await resolve_chapters(native, [], ai)
    assert chapters == native and cost == 0.0
    ai.translate_chapters.assert_not_called()
    ai.generate_chapters.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_translates_nonkorean_native():
    ai = AsyncMock()
    ai.translate_chapters.return_value = ([{"t": 0, "label": "인트로"}], 0.01, "m")
    native = [{"t": 0, "label": "Intro"}]
    chapters, cost, model = await resolve_chapters(native, [], ai)
    assert chapters == [{"t": 0, "label": "인트로"}] and cost == 0.01
    ai.translate_chapters.assert_awaited_once_with(native)
    ai.generate_chapters.assert_not_called()
