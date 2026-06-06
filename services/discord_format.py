"""노트 dict → Discord 임베드용 dict 변환. discord 의존 없는 순수 함수."""

MAX_SUMMARY = 1500
MAX_FIELD = 1024
MAX_INSIGHTS = 5
MAX_CHAPTERS = 8


def seconds_to_mmss(seconds) -> str:
    s = max(0, int(seconds or 0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def chapter_link(video_id: str, t, label: str) -> str:
    secs = max(0, int(t or 0))
    return f"[{seconds_to_mmss(secs)} {label}](https://youtu.be/{video_id}?t={secs})"


def _truncate(text, limit: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_embed(note: dict) -> dict:
    """note: get_note 결과(+ video_id, read_url). 반환: discord.Embed 변환용 dict."""
    fields = []

    insights = note.get("insights") or []
    if insights:
        body = "\n".join(f"• {_truncate(i, 200)}" for i in insights[:MAX_INSIGHTS])
        fields.append({"name": "💡 핵심", "value": _truncate(body, MAX_FIELD), "inline": False})

    video_id = note.get("video_id")
    chapters = note.get("timeline") or []
    if video_id and chapters:
        lines = []
        for c in chapters[:MAX_CHAPTERS]:
            t = c.get("t")
            if t is None:
                continue
            lines.append(chapter_link(video_id, t, _truncate(c.get("label") or "", 60)))
        if lines:
            fields.append({"name": "⏱ 타임라인", "value": _truncate("\n".join(lines), MAX_FIELD), "inline": False})

    tags = note.get("tags") or []
    if tags:
        fields.append({"name": "🏷 태그", "value": _truncate(" ".join(f"#{t}" for t in tags), MAX_FIELD), "inline": False})

    read_url = note.get("read_url")
    if read_url:
        fields.append({"name": "📖 전체 노트", "value": f"[열기]({read_url})", "inline": False})

    return {
        "title": _truncate(note.get("title") or "제목 없음", 256),
        "description": _truncate(note.get("summary") or "", MAX_SUMMARY),
        "url": read_url,
        "fields": fields,
    }
