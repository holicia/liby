import re
from services.extractor import segments_to_transcript

_HANGUL = re.compile(r'[가-힣]')


def _labels_are_korean(chapters: list[dict]) -> bool:
    """챕터 라벨에 한글이 하나라도 있으면 한국어로 간주."""
    text = " ".join(str(c.get("label", "")) for c in chapters)
    return bool(_HANGUL.search(text))


async def resolve_chapters(
    native_chapters: list[dict] | None,
    segments: list[dict],
    ai,
) -> tuple[list[dict], float, str]:
    """네이티브 챕터 우선. 비한국어 라벨이면 번역, 없으면 AI 생성."""
    if native_chapters:
        if _labels_are_korean(native_chapters):
            return native_chapters, 0.0, ""
        return await ai.translate_chapters(native_chapters)
    if not segments:
        return [], 0.0, ""
    transcript = segments_to_transcript(segments)
    return await ai.generate_chapters(transcript)
