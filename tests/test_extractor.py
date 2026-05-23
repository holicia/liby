import pytest
from unittest.mock import patch, MagicMock
from services.extractor import extract_youtube, extract_pdf, chunk_text


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
