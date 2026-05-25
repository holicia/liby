import pytest
from unittest.mock import patch, MagicMock
from services.extractor import extract_youtube, extract_pdf, chunk_text
from services.extractor import (
    _parse_native_chapters, _build_segments, segments_to_transcript, youtube_video_id,
)


def test_chunk_text_splits_long_text():
    text = "단어 " * 5000
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1100 for c in chunks)


def test_chunk_text_short_text_returns_one_chunk():
    text = "짧은 텍스트"
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_extract_youtube_returns_text_and_video_id():
    mock_transcript = [{"text": "안녕하세요", "start": 0.0}, {"text": "반갑습니다", "start": 2.0}]
    with patch("services.extractor.YouTubeTranscriptApi.get_transcript", return_value=mock_transcript):
        text, video_id = await extract_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert "안녕하세요" in text
    assert video_id == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_extract_pdf_returns_text(tmp_path):
    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.get_text.return_value = "PDF 내용입니다."
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=False)

    with patch("services.extractor.fitz.open", return_value=mock_doc):
        text = await extract_pdf("/fake/path.pdf")
    assert "PDF 내용" in text


def test_parse_native_chapters_present():
    raw = [{"start_time": 0, "title": "인트로"}, {"start_time": 12.7, "title": "본론"}]
    out = _parse_native_chapters(raw)
    assert out == [{"t": 0, "label": "인트로"}, {"t": 12, "label": "본론"}]

def test_parse_native_chapters_absent():
    assert _parse_native_chapters(None) is None
    assert _parse_native_chapters([]) is None

def test_build_segments_from_json3():
    data = {"events": [
        {"tStartMs": 0, "segs": [{"utf8": "안녕"}, {"utf8": "하세요"}]},
        {"tStartMs": 2500, "segs": [{"utf8": "반갑습니다"}]},
        {"tStartMs": 4000, "segs": [{"utf8": "\n"}]},
    ]}
    segs = _build_segments(data)
    assert segs == [{"t": 0, "text": "안녕하세요"}, {"t": 2, "text": "반갑습니다"}]

def testsegments_to_transcript_formats_timestamps():
    segs = [{"t": 0, "text": "시작"}, {"t": 75, "text": "중간"}]
    txt = segments_to_transcript(segs)
    assert "[0:00] 시작" in txt
    assert "[1:15] 중간" in txt

def test_youtube_video_id_ok_and_none():
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("not a url") is None

def test_parse_native_chapters_all_missing_start_returns_none():
    assert _parse_native_chapters([{"title": "제목만"}, {"title": "또"}]) is None

def test_parse_native_chapters_blank_title_defaults():
    assert _parse_native_chapters([{"start_time": 5, "title": "   "}]) == [{"t": 5, "label": "챕터"}]

def test_build_segments_empty_events_returns_empty():
    assert _build_segments({"events": []}) == []
    assert _build_segments({}) == []

def testsegments_to_transcript_empty_returns_empty_string():
    assert segments_to_transcript([]) == ""
