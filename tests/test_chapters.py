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
    ai.generate_chapters.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_falls_back_to_ai():
    ai = AsyncMock()
    ai.generate_chapters.return_value = ([{"t": 0, "label": "AI"}], 0.01, "claude-sonnet-4-6")
    chapters, cost, model = await resolve_chapters(None, [{"t": 0, "text": "안녕"}], ai)
    assert chapters == [{"t": 0, "label": "AI"}]
    assert cost == 0.01
    ai.generate_chapters.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_no_segments_returns_empty():
    ai = AsyncMock()
    chapters, cost, model = await resolve_chapters(None, [], ai)
    assert chapters == []
    assert cost == 0.0
    ai.generate_chapters.assert_not_called()
