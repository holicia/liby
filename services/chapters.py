from services.extractor import _segments_to_transcript


async def resolve_chapters(native_chapters, segments, ai):
    """네이티브 챕터가 있으면 그대로(비용 0), 없으면 AI로 생성.

    반환: (chapters: list[dict], cost_usd: float, model: str)
    """
    if native_chapters:
        return native_chapters, 0.0, ""
    if not segments:
        return [], 0.0, ""
    transcript = _segments_to_transcript(segments)
    return await ai.generate_chapters(transcript)
