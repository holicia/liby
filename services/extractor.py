import re
import fitz
from youtube_transcript_api import YouTubeTranscriptApi


def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"YouTube ID를 추출할 수 없습니다: {url}")


def chunk_text(text: str, max_chars: int = 10000) -> list[str]:
    """Split text into chunks while preserving paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")

    current = ""
    for p in paragraphs:
        # If adding this paragraph would exceed max_chars, flush current and start new
        test_len = len(current) + (len("\n\n") if current else 0) + len(p)
        if test_len > max_chars:
            if current:
                chunks.append(current.strip())
            current = p
        else:
            current += ("\n\n" + p) if current else p

    if current.strip():
        chunks.append(current.strip())

    # If we still have only one chunk but it's too long, split it by character limit
    if len(chunks) == 1 and len(chunks[0]) > max_chars:
        chunk = chunks[0]
        chunks = [chunk[i:i+max_chars] for i in range(0, len(chunk), max_chars)]

    return chunks if chunks else [text[i:i+max_chars] for i in range(0, len(text), max_chars)]


async def extract_youtube(url: str) -> tuple[str, str]:
    """Extract transcript from YouTube video and return (text, video_id)."""
    video_id = _extract_video_id(url)
    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko", "en"])
    text = " ".join(t["text"] for t in transcript)
    return text, video_id


async def extract_pdf(file_path: str) -> str:
    """Extract text from PDF file."""
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text
