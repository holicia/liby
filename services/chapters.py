from services.extractor import segments_to_transcript


async def resolve_chapters(
    native_chapters: list[dict] | None,
    segments: list[dict],
    ai,
) -> tuple[list[dict], float, str]:
    """네이티브 챕터가 있으면 그대로(비용 0), 없으면 AI로 생성.

    반환: (chapters, cost_usd, model)
    """
    if native_chapters:
        return native_chapters, 0.0, ""
    if not segments:
        return [], 0.0, ""
    transcript = segments_to_transcript(segments)
    return await ai.generate_chapters(transcript)
