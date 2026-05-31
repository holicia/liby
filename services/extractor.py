import asyncio
import base64
import json
import re
import urllib.request
import fitz
import yt_dlp


def _extract_video_id(url: str) -> str:
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


def youtube_video_id(url: str) -> str | None:
    """source_url에서 video_id 추출, 실패 시 None (모달 임베드 판단용)."""
    try:
        return _extract_video_id(url)
    except ValueError:
        return None


def _parse_native_chapters(chapters: list | None) -> list[dict] | None:
    """yt-dlp info['chapters'] → [{t, label}]. 없으면 None."""
    if not chapters:
        return None
    out = []
    for c in chapters:
        start = c.get("start_time")
        if start is None:
            continue
        title = (c.get("title") or "").strip()
        out.append({"t": int(start), "label": title or "챕터"})
    return out or None


def _build_segments(json3_data: dict) -> list[dict]:
    """json3 자막 → [{t: 초, text}] 타임스탬프 세그먼트."""
    segments = []
    for ev in json3_data.get("events", []):
        text = "".join(seg.get("utf8", "") for seg in ev.get("segs", [])).strip()
        if not text:  # strip 후 빈 문자열(자막 사이 개행 이벤트 등) 제외
            continue
        segments.append({"t": int(ev.get("tStartMs", 0) // 1000), "text": text})
    return segments


def segments_to_transcript(segments: list[dict]) -> str:
    """[{t,text}] → '[m:ss] text' 줄 단위 문자열 (AI 챕터 입력용)."""
    lines = []
    for s in segments:
        m, sec = divmod(int(s["t"]), 60)
        lines.append(f"[{m}:{sec:02d}] {s['text']}")
    return "\n".join(lines)


def _fetch_transcript_sync(video_id: str) -> str:
    ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})

    chosen = None
    for lang in ["ko", "en"]:
        if lang in subs:
            chosen = subs[lang]
            break
        if lang in auto_subs:
            chosen = auto_subs[lang]
            break

    if not chosen:
        raise ValueError(f"트랜스크립트를 찾을 수 없습니다: {video_id}")

    j3 = next((s for s in chosen if s.get("ext") == "json3"), chosen[0])
    req = urllib.request.Request(j3["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)
    texts = [
        seg.get("utf8", "").strip()
        for ev in data.get("events", [])
        for seg in ev.get("segs", [])
        if seg.get("utf8", "").strip() not in ("", "\n")
    ]
    return " ".join(texts)


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
    video_id = _extract_video_id(url)
    # yt-dlp는 동기 라이브러리이므로 executor로 실행해 이벤트 루프를 블록하지 않음
    text = await asyncio.get_event_loop().run_in_executor(None, _fetch_transcript_sync, video_id)
    return text, video_id


def _fetch_full_sync(video_id: str) -> dict:
    ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    native_chapters = _parse_native_chapters(info.get("chapters"))

    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})
    chosen = None
    for lang in ["ko", "en"]:
        if lang in subs:
            chosen = subs[lang]
            break
        if lang in auto_subs:
            chosen = auto_subs[lang]
            break
    if not chosen:  # None 또는 빈 리스트 모두 여기서 차단 → 아래 chosen[0] 안전
        raise ValueError(f"트랜스크립트를 찾을 수 없습니다: {video_id}")

    j3 = next((s for s in chosen if s.get("ext") == "json3"), chosen[0])
    req = urllib.request.Request(j3["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    segments = _build_segments(data)
    text = " ".join(s["text"] for s in segments)
    return {
        "text": text,
        "video_id": video_id,
        "native_chapters": native_chapters,
        "segments": segments,
    }


async def extract_youtube_full(url: str) -> dict:
    video_id = _extract_video_id(url)
    return await asyncio.get_running_loop().run_in_executor(None, _fetch_full_sync, video_id)


def _fetch_youtube_title_sync(url: str) -> str | None:
    """yt-dlp 메타데이터로 영상 제목만 가져온다(자막/포맷 처리 생략으로 빠름). 실패 시 None."""
    try:
        opts = {"skip_download": True, "quiet": True, "no_warnings": True, "extract_flat": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
        return info.get("title")
    except Exception:
        return None


async def youtube_title(url: str) -> str | None:
    return await asyncio.get_running_loop().run_in_executor(None, _fetch_youtube_title_sync, url)


def _github_api(path: str) -> dict:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "liby/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _fetch_github_sync(url: str) -> tuple[str, str]:
    m = re.match(r"https?://github\.com/([^/]+)/([^/?\s#]+)", url)
    if not m:
        raise ValueError(f"GitHub URL 형식이 올바르지 않습니다: {url}")
    owner, repo = m.group(1), m.group(2).removesuffix(".git")

    meta = _github_api(f"/repos/{owner}/{repo}")

    try:
        readme_data = _github_api(f"/repos/{owner}/{repo}/readme")
        readme = base64.b64decode(readme_data["content"]).decode("utf-8", errors="ignore")[:8000]
    except Exception:
        readme = "(README 없음)"

    try:
        tree_data = _github_api(f"/repos/{owner}/{repo}/git/trees/HEAD?recursive=1")
        files = [t["path"] for t in tree_data.get("tree", []) if t["type"] == "blob"]
    except Exception:
        files = []

    KEY_FILES = ["requirements.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "setup.py"]
    key_contents = []
    for kf in KEY_FILES:
        if kf in files:
            try:
                fd = _github_api(f"/repos/{owner}/{repo}/contents/{kf}")
                content = base64.b64decode(fd["content"]).decode("utf-8", errors="ignore")[:2000]
                key_contents.append(f"=== {kf} ===\n{content}")
            except Exception:
                pass

    parts = [
        f"# {owner}/{repo}",
        f"설명: {meta.get('description') or '없음'}",
        f"주 언어: {meta.get('language') or '미분류'}",
        f"토픽: {', '.join(meta.get('topics', []) or [])}",
        f"스타: {meta.get('stargazers_count', 0)}",
        f"\n## README\n{readme}",
        f"\n## 파일 구조 ({len(files)}개)\n" + "\n".join(files[:80]),
    ]
    if key_contents:
        parts.append("\n## 주요 설정 파일\n" + "\n\n".join(key_contents))

    return "\n".join(parts), f"{owner}/{repo}"


async def extract_github_repo(url: str) -> tuple[str, str]:
    return await asyncio.get_event_loop().run_in_executor(None, _fetch_github_sync, url)


async def extract_pdf(file_path: str) -> str:
    """Extract text from PDF file."""
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text


def _chunk_for_llm(text: str, max_chars: int = 12000) -> list[str]:
    """text를 줄(\n) 단위로 묶어 max_chars 한도 안의 chunk list 반환.
    빈 text는 []. 한 줄이 max_chars보다 길면 그 줄 단독 chunk(잘리지 않음).
    합쳐도 개행을 손실 없이 원본 text 복원 가능."""
    if not text:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_size = len(line) + 1
        if current and current_len + line_size > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks
