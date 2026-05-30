import os
import pytest
from unittest.mock import patch
from services.capture import capture_chapter_screenshots


@pytest.mark.asyncio
async def test_capture_skips_when_chapters_empty(tmp_path):
    result = await capture_chapter_screenshots(
        "https://youtu.be/x", [], str(tmp_path), "slug")
    assert result == []


@pytest.mark.asyncio
async def test_capture_adds_image_path_on_success(tmp_path):
    chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}]
    with patch("services.capture._capture_one_sync", return_value=True):
        result = await capture_chapter_screenshots(
            "https://youtu.be/x", chapters, str(tmp_path), "myslug")
    assert result[0] == {"t": 0, "label": "A", "image": "myslug/ch-1.jpg"}
    assert result[1] == {"t": 90, "label": "B", "image": "myslug/ch-2.jpg"}
    assert (tmp_path / "youtube" / "myslug").is_dir()


@pytest.mark.asyncio
async def test_capture_skips_failed_chapter_continues_others(tmp_path):
    chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}, {"t": 180, "label": "C"}]
    with patch("services.capture._capture_one_sync", side_effect=[True, False, True]):
        result = await capture_chapter_screenshots(
            "https://youtu.be/x", chapters, str(tmp_path), "s")
    assert "image" in result[0]
    assert "image" not in result[1]
    assert "image" in result[2]


@pytest.mark.asyncio
async def test_capture_returns_chapters_without_images_when_all_fail(tmp_path):
    chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}]
    with patch("services.capture._capture_one_sync", return_value=False):
        result = await capture_chapter_screenshots(
            "https://youtu.be/x", chapters, str(tmp_path), "s")
    assert all("image" not in ch for ch in result)
    assert result[0]["t"] == 0 and result[0]["label"] == "A"
