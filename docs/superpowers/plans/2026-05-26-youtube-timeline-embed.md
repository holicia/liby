# YouTube 타임라인 + 임베드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YouTube 노트 상세 모달에 영상 임베드와 (네이티브 우선, 없으면 AI) 챕터 타임라인을 추가하고, 챕터 클릭 시 IFrame Player API로 영상을 해당 지점으로 이동시킨다.

**Architecture:** yt-dlp 단일 호출로 자막 텍스트 + video_id + 네이티브 챕터 + 타임스탬프 세그먼트를 추출한다. 챕터는 네이티브가 있으면 그대로, 없으면 AI(`generate_chapters`)로 생성해 `items.timeline`(JSON)에 저장한다. 신규 youtube 분석은 자동 생성, 기존 노트는 모달의 "타임라인 생성" 버튼으로 온디맨드 백필한다. 모달은 IFrame Player API로 영상을 임베드하고 챕터 클릭 시 `seekTo`로 이동한다.

**Tech Stack:** FastAPI, HTMX(1.9.12), Jinja2, Tailwind(CDN), SQLite(aiosqlite), yt-dlp, Anthropic/OpenAI SDK, pytest + pytest-asyncio + httpx(ASGITransport), YouTube IFrame Player API.

---

## 데이터 형태 (전 태스크 공통)

- **Chapter**: `{"t": <초 int>, "label": <str>}`
- **Segment**: `{"t": <초 int>, "text": <str>}`
- `extract_youtube_full(url)` 반환 dict: `{"text": str, "video_id": str, "native_chapters": list[Chapter] | None, "segments": list[Segment]}`
- `AIProvider.generate_chapters(transcript: str)` → `(chapters: list[Chapter], cost_usd: float, model: str)`
- `resolve_chapters(native_chapters, segments, ai)` → `(chapters, cost_usd, model)`

## 파일 구조

| 파일 | 변경 |
|------|------|
| `models.py` | `items.timeline` 컬럼 마이그레이션 |
| `services/extractor.py` | 챕터/세그먼트 헬퍼 + `extract_youtube_full` + `youtube_video_id` |
| `services/ai/base.py` | `generate_chapters` 기본 구현(no-op) |
| `services/ai/claude.py`,`openai_provider.py` | `generate_chapters` 구현 + `CHAPTERS_PROMPT` |
| `services/chapters.py` | **신규** `resolve_chapters` 코디네이터 |
| `services/storage.py` | `save_note(timeline=)`, `set_timeline`, `_JSON_FIELDS`에 timeline |
| `routers/youtube.py` | 분석 시 타임라인 생성·저장 |
| `routers/items.py` | detail에 video_id 전달 + `POST /{id}/timeline` 백필 |
| `templates/partials/note_detail_modal.html` | 임베드 + 챕터 목록 + 생성 버튼 |
| `templates/base.html` | IFrame API 로드 + `initYtPlayer`/`ytSeek` + 모달 정리 |
| `tests/test_*.py` | 각 계층 테스트 |

**테스트 실행 (Windows):** `python -m pytest <경로>::<테스트> -v`. 기존 3건(`test_extractor.py::test_extract_youtube_returns_text_and_video_id`, `test_routes_pdf.py::test_analyze_pdf_returns_note_card`, `test_routes_youtube.py::test_analyze_youtube_returns_htmx_fragment`)은 이 기능과 무관한 사전 실패 — 새 실패만 없으면 됨.

---

## Task 1: `items.timeline` 컬럼 마이그레이션

**Files:** Modify `models.py`; Test `tests/test_models.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_models.py` 끝에

```python
@pytest.mark.asyncio
async def test_init_db_adds_timeline_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "timeline" in cols
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_models.py -v` → 새 테스트 FAIL.

- [ ] **Step 3: 구현** — `models.py`

기존 `_ensure_project_id_column`을 일반 헬퍼로 교체하고 timeline도 추가. 기존 함수를 다음으로 대체:
```python
async def _ensure_column(db, column: str, decl: str) -> None:
    cursor = await db.execute("PRAGMA table_info(items)")
    cols = [r[1] for r in await cursor.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE items ADD COLUMN {column} {decl}")
```
`init_db` 본문에서 마이그레이션 호출부를 다음으로 변경:
```python
        await db.execute(CREATE_PROJECTS)
        await _ensure_column(db, "project_id", "INTEGER")
        await _ensure_column(db, "timeline", "TEXT")
        await db.commit()
```
(기존 `_ensure_project_id_column` 정의/호출은 제거하고 위 일반 헬퍼로 대체. `CREATE_PROJECTS` 등 나머지는 그대로.)

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_models.py -v` → 전체 PASS (기존 project_id 테스트 포함).

- [ ] **Step 5: 커밋**
```bash
git add models.py tests/test_models.py
git commit -m "feat: add items.timeline column migration"
```

---

## Task 2: 추출 — 챕터/세그먼트 헬퍼 + extract_youtube_full

**Files:** Modify `services/extractor.py`; Test `tests/test_extractor.py`

현재 `extractor.py`에는 `_extract_video_id(url)`, `_fetch_transcript_sync(video_id)`(json3 자막에서 utf8 텍스트만 join), `extract_youtube(url) -> (text, video_id)`가 있다. `extract_youtube`는 그대로 두고 새 함수/헬퍼를 추가한다.

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_extractor.py` 끝에

```python
from services.extractor import (
    _parse_native_chapters, _build_segments, _segments_to_transcript, youtube_video_id,
)

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

def test_segments_to_transcript_formats_timestamps():
    segs = [{"t": 0, "text": "시작"}, {"t": 75, "text": "중간"}]
    txt = _segments_to_transcript(segs)
    assert "[0:00] 시작" in txt
    assert "[1:15] 중간" in txt

def test_youtube_video_id_ok_and_none():
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("not a url") is None
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_extractor.py -v` → 새 테스트 ImportError/FAIL.

- [ ] **Step 3: 구현** — `services/extractor.py`에 추가

`_extract_video_id` 아래에 추가:
```python
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
        title = (c.get("title") or "").strip()
        start = c.get("start_time")
        if start is None:
            continue
        out.append({"t": int(start), "label": title or "챕터"})
    return out or None


def _build_segments(json3_data: dict) -> list[dict]:
    """json3 자막 → [{t: 초, text}] 타임스탬프 세그먼트."""
    segments = []
    for ev in json3_data.get("events", []):
        text = "".join(seg.get("utf8", "") for seg in ev.get("segs", [])).strip()
        if not text or text == "\n":
            continue
        segments.append({"t": int(ev.get("tStartMs", 0) // 1000), "text": text})
    return segments


def _segments_to_transcript(segments: list[dict]) -> str:
    """[{t,text}] → '[m:ss] text' 줄 단위 문자열 (AI 챕터 입력용)."""
    lines = []
    for s in segments:
        m, sec = divmod(int(s["t"]), 60)
        lines.append(f"[{m}:{sec:02d}] {s['text']}")
    return "\n".join(lines)
```

이어서 `_fetch_transcript_sync`를 리팩터링해 json3 원본 데이터도 돌려주도록 보조 함수를 추가하고, 단일 `extract_info` 호출로 모든 것을 모으는 동기 함수 + async 래퍼를 추가한다. `extract_youtube` 정의 위/아래 적절한 위치에 추가:
```python
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
            chosen = subs[lang]; break
        if lang in auto_subs:
            chosen = auto_subs[lang]; break
    if not chosen:
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
    return await asyncio.get_event_loop().run_in_executor(None, _fetch_full_sync, video_id)
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_extractor.py -v` → 새 5개 PASS (기존 stale 실패 1건은 그대로 무시).

- [ ] **Step 5: 커밋**
```bash
git add services/extractor.py tests/test_extractor.py
git commit -m "feat: extract_youtube_full with native chapters and timestamped segments"
```

---

## Task 3: AI `generate_chapters` (base + claude + openai)

**Files:** Modify `services/ai/base.py`, `services/ai/claude.py`, `services/ai/openai_provider.py`; Test `tests/test_claude_provider.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_claude_provider.py` 끝에

```python
@pytest.mark.asyncio
async def test_generate_chapters_parses_json(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{"chapters": [{"t": 0, "label": "인트로"}, {"t": 150, "label": "핵심 개념"}]}
""")]
    mock_response.usage = MagicMock(input_tokens=200, output_tokens=80)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        chapters, cost, model = await provider.generate_chapters("[0:00] 안녕\n[2:30] 개념")
    assert chapters == [{"t": 0, "label": "인트로"}, {"t": 150, "label": "핵심 개념"}]
    assert cost > 0
    assert model
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_claude_provider.py -v` → FAIL.

- [ ] **Step 3: 구현**

(3a) `services/ai/base.py` — `AIProvider`에 기본 구현(no-op) 추가 (다른 프로바이더가 미구현해도 안전):
```python
    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        """타임스탬프 자막 → [{t,label}] 챕터. 기본은 빈 결과(프로바이더가 오버라이드)."""
        return [], 0.0, ""
```
(이 메서드는 `@abstractmethod`가 아님 — 기본 구현 제공.)

(3b) `services/ai/claude.py` — 프롬프트 상수 추가(다른 프롬프트들 근처):
```python
CHAPTERS_PROMPT = """다음은 타임스탬프가 붙은 영상 자막입니다. 영상을 5~12개의 의미 단위 챕터로 나누세요.
각 챕터는 시작 시각(초)과 짧은 제목(라벨)으로 표현합니다. 시간 오름차순, 첫 챕터는 t=0.

자막:
{transcript}

JSON으로만 응답하세요:
{{"chapters": [{{"t": 0, "label": "인트로"}}, {{"t": 150, "label": "핵심 개념"}}]}}"""
```
`ClaudeProvider`에 메서드 추가:
```python
    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        model = config.CLAUDE_MODELS["tier2"]
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        resp = await self._client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(resp.content[0].text)
        cost = _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        chapters = [
            {"t": int(c["t"]), "label": str(c.get("label", "")).strip()}
            for c in data.get("chapters", []) if "t" in c
        ]
        chapters.sort(key=lambda c: c["t"])
        return chapters, cost, model
```

(3c) `services/ai/openai_provider.py` — `CHAPTERS_PROMPT`를 claude에서 import에 추가(`from services.ai.claude import TIER2_PROMPT, TIER2_CODE_PROMPT, TIER3_PROMPT, CHAPTERS_PROMPT`), `OpenAIProvider`에 추가:
```python
    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        model = config.GPT_MODELS["tier2"]
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        cost = _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        chapters = [
            {"t": int(c["t"]), "label": str(c.get("label", "")).strip()}
            for c in data.get("chapters", []) if "t" in c
        ]
        chapters.sort(key=lambda c: c["t"])
        return chapters, cost, model
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_claude_provider.py -v` → PASS.

- [ ] **Step 5: 커밋**
```bash
git add services/ai/base.py services/ai/claude.py services/ai/openai_provider.py tests/test_claude_provider.py
git commit -m "feat: AIProvider.generate_chapters for timeline chapters"
```

---

## Task 4: 저장 — timeline 컬럼 save/get + set_timeline

**Files:** Modify `services/storage.py`; Test `tests/test_storage.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_storage.py` 끝에 (`set_timeline` import 추가)

상단 import에 추가:
```python
from services.storage import set_timeline
```
테스트:
```python
@pytest.mark.asyncio
async def test_save_note_with_timeline(db, tmp_path):
    chapters = [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", timeline=chapters)
    note = await get_note(db, nid)
    assert note["timeline"] == chapters  # _parse_row가 JSON 역직렬화

@pytest.mark.asyncio
async def test_save_note_timeline_defaults_empty(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="pdf",
                          source_url="u", result=make_result(), ai_provider="claude")
    note = await get_note(db, nid)
    assert note["timeline"] in (None, [], "")

@pytest.mark.asyncio
async def test_set_timeline_updates(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    await set_timeline(db, nid, [{"t": 0, "label": "A"}])
    note = await get_note(db, nid)
    assert note["timeline"] == [{"t": 0, "label": "A"}]
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_storage.py -v` → 새 테스트 FAIL.

- [ ] **Step 3: 구현** — `services/storage.py`

(3a) `_JSON_FIELDS` 튜플에 `"timeline"` 추가:
```python
_JSON_FIELDS = ("tags", "key_points", "sections", "main_arguments",
                "insights", "questions_raised", "related_concepts", "ai_models", "timeline")
```

(3b) `save_note` 시그니처에 `timeline: list | None = None` 추가(`project_id` 다음), INSERT의 컬럼/값/플레이스홀더에 `timeline` 추가. 컬럼 목록 끝에 `, timeline`, VALUES에 `?` 하나 추가, 값 튜플 끝에 `json.dumps(timeline or [], ensure_ascii=False)` 추가. 최종 형태:
```python
async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_id: int | None = None,
    timeline: list | None = None,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-{_safe_filename(result.title)}.md"
    subdir = os.path.join(vault_path, source_type)
    os.makedirs(subdir, exist_ok=True)
    md_path = os.path.join(subdir, filename)

    async with aiosqlite.connect(db_path) as db:
        proj_name = await _project_name(db, project_id)
        md_content = _make_md_content(source_type, source_url, result, ai_provider, proj_name)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, main_arguments, insights, questions_raised,
                related_concepts, ai_provider, ai_models, api_cost_usd, md_file_path,
                project_id, timeline)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, result.title, source_url, result.summary,
                json.dumps(result.key_points, ensure_ascii=False),
                json.dumps(result.sections, ensure_ascii=False),
                json.dumps(result.tags, ensure_ascii=False),
                result.suggested_topic, result.summary_mode,
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                ai_provider,
                json.dumps(result.models_used, ensure_ascii=False),
                result.cost_usd, md_path, project_id,
                json.dumps(timeline or [], ensure_ascii=False),
            )
        )
        await db.commit()
        return cursor.lastrowid
```

(3c) 파일 끝에 `set_timeline` 추가:
```python
async def set_timeline(db_path: str, note_id: int, chapters: list) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE items SET timeline = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(chapters or [], ensure_ascii=False), note_id),
        )
        await db.commit()
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_storage.py -v` → 전체 PASS.

- [ ] **Step 5: 커밋**
```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: store timeline on save_note and set_timeline"
```

---

## Task 5: `resolve_chapters` 코디네이터

**Files:** Create `services/chapters.py`; Test `tests/test_chapters.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_chapters.py`

```python
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
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_chapters.py -v` → ImportError/FAIL.

- [ ] **Step 3: 구현** — `services/chapters.py`

```python
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
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_chapters.py -v` → PASS.

- [ ] **Step 5: 커밋**
```bash
git add services/chapters.py tests/test_chapters.py
git commit -m "feat: resolve_chapters native-first with AI fallback"
```

---

## Task 6: youtube 라우터 — 분석 시 타임라인 생성

**Files:** Modify `routers/youtube.py`; Test `tests/test_routes_youtube.py`

현재 `analyze_youtube`의 `do_work`는 `extract_youtube` → `summarize` → `save_note` → `record_api_cost` 순서다. `extract_youtube_full` + `resolve_chapters`로 확장한다.

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_routes_youtube.py` 끝에

```python
@pytest.mark.asyncio
async def test_youtube_do_work_generates_timeline():
    import routers.youtube as yt
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn

    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=1, reading_time_min=1, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        cost_usd=0.0, models_used=["m"])
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": [{"t": 0, "label": "C"}], "segments": []}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([{"t": 0, "label": "C"}], 0.0, "")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc", "provider": "claude", "mode": "quick"})
        # 큐에 들어간 do_work를 직접 실행
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    assert mock_save.call_args.kwargs.get("timeline") == [{"t": 0, "label": "C"}]
```
(상단 import에 `AsyncMock, MagicMock`이 없으면 추가: `from unittest.mock import patch, AsyncMock, MagicMock`.)

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_routes_youtube.py::test_youtube_do_work_generates_timeline -v` → FAIL.

- [ ] **Step 3: 구현** — `routers/youtube.py`

import 변경: `from services.extractor import extract_youtube` → `from services.extractor import extract_youtube_full`. 추가: `from services.chapters import resolve_chapters`.

`do_work`를 다음으로 교체:
```python
    async def do_work(t):
        t.progress = "YouTube 자막 추출 중..."
        data = await extract_youtube_full(url)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(data["text"], "youtube", mode, topics)
        t.title = result.title
        t.progress = "타임라인 생성 중..."
        chapters, ch_cost, ch_model = await resolve_chapters(
            data["native_chapters"], data["segments"], ai)
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd, item_id=note_id,
        )
        if ch_cost > 0:
            await record_api_cost(
                config.DB_PATH, ai.name(), model=ch_model,
                input_tokens=0, output_tokens=0, cost_usd=ch_cost, item_id=note_id,
            )
        t.note_id = note_id
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_routes_youtube.py -v` → 새 테스트 PASS (기존 stale 실패 1건 무시, 새 실패 없음).

- [ ] **Step 5: 커밋**
```bash
git add routers/youtube.py tests/test_routes_youtube.py
git commit -m "feat: generate and store timeline during youtube analysis"
```

---

## Task 7: items 라우터 — detail에 video_id + 타임라인 백필 엔드포인트

**Files:** Modify `routers/items.py`; Test `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_routes_items.py` 끝에

`MOCK_NOTE`는 `type: "youtube"`, `source_url`이 있으므로 video_id 추출 가능.
```python
@pytest.mark.asyncio
async def test_detail_passes_video_id_for_youtube():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "yt-player" in resp.text  # 임베드 플레이스홀더 렌더

@pytest.mark.asyncio
async def test_backfill_timeline_calls_set_timeline():
    note = dict(MOCK_NOTE)
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None, "segments": [{"t": 0, "text": "a"}]}), \
         patch("routers.items.get_provider") as mock_get, \
         patch("routers.items.resolve_chapters", new_callable=AsyncMock, return_value=([{"t": 0, "label": "C"}], 0.0, "")), \
         patch("routers.items.set_timeline", new_callable=AsyncMock) as mock_set, \
         patch("routers.items.record_api_cost", new_callable=AsyncMock):
        mock_get.return_value = MagicMock(name=lambda: "claude")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/timeline")
    assert resp.status_code == 200
    mock_set.assert_awaited_once()
```
(상단 import에 `AsyncMock, MagicMock`가 없으면 추가.)

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_routes_items.py -v` → 새 테스트 FAIL.

- [ ] **Step 3: 구현** — `routers/items.py`

import 추가:
```python
from services.extractor import youtube_video_id, extract_youtube_full
from services.chapters import resolve_chapters
```
그리고 storage import 블록에 `set_timeline` 추가.

`get_item_detail` 수정 — youtube면 video_id 전달:
```python
@router.get("/{note_id}/detail")
async def get_item_detail(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    video_id = None
    if note and note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": note, "video_id": video_id},
    )
```

`get_item_detail` 아래(또는 `/{note_id}/project` 근처)에 백필 엔드포인트 추가:
```python
@router.post("/{note_id}/timeline")
async def backfill_timeline(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note or not note.get("source_url"):
        return templates.TemplateResponse(request, "partials/note_detail_modal.html", {"note": note, "video_id": None})
    data = await extract_youtube_full(note["source_url"])
    provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))
    chapters, cost, model = await resolve_chapters(data["native_chapters"], data["segments"], provider)
    await set_timeline(config.DB_PATH, note_id, chapters)
    if cost > 0:
        await record_api_cost(config.DB_PATH, provider.name(), model, 0, 0, cost, note_id)
    updated = await get_note(config.DB_PATH, note_id)
    video_id = youtube_video_id(updated["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": updated, "video_id": video_id},
    )
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_routes_items.py -v` → 전체 PASS.

- [ ] **Step 5: 커밋**
```bash
git add routers/items.py tests/test_routes_items.py
git commit -m "feat: detail passes video_id and on-demand timeline backfill endpoint"
```

---

## Task 8: 프론트엔드 — 모달 임베드 + 챕터 + IFrame Player

**Files:** Modify `templates/partials/note_detail_modal.html`, `templates/base.html`
검증: 브라우저 수동 (HTMX/JS).

- [ ] **Step 1: `note_detail_modal.html` — 영상/챕터 섹션 추가**

헤더 블록(닫기 버튼 + 헤더 div) 다음, `<!-- 태그 & 주제 -->` 위에 삽입:
```html
    <!-- 영상 임베드 + 챕터 -->
    {% if video_id %}
    <div class="mb-4">
      <div class="aspect-video w-full rounded-lg overflow-hidden bg-black mb-3">
        <div id="yt-player" data-video-id="{{ video_id }}" class="w-full h-full"></div>
      </div>
      {% set tl = note.timeline if note.timeline is not string else (note.timeline | fromjson) %}
      {% if tl %}
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">챕터</h3>
      <ul class="space-y-0.5 max-h-48 overflow-y-auto">
        {% for ch in tl %}
        <li>
          <button type="button" onclick="ytSeek({{ ch.t }})"
                  class="w-full text-left flex gap-2 text-[12px] text-gray-700 dark:text-gray-300 hover:bg-[#EAF4EE] dark:hover:bg-[#14291E] rounded px-2 py-1 transition-colors">
            <span class="text-[#1F6F4A] dark:text-[#34A66A] font-mono flex-shrink-0">{{ "%d:%02d"|format(ch.t // 60, ch.t % 60) }}</span>
            <span class="truncate">{{ ch.label }}</span>
          </button>
        </li>
        {% endfor %}
      </ul>
      {% elif note.type == 'youtube' %}
      <button hx-post="/api/items/{{ note.id }}/timeline"
              hx-target="#note-modal" hx-swap="innerHTML"
              class="text-xs bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] border border-[#A8CBB2] dark:border-[#2D6B4A] rounded-lg px-3 py-1.5 font-semibold hover:bg-[#1F6F4A] hover:text-white transition-colors">
        ⏱ 타임라인 생성
      </button>
      <span class="htmx-indicator text-[11px] text-gray-400 ml-2">생성 중...</span>
      {% endif %}
    </div>
    {% endif %}
```

- [ ] **Step 2: `base.html` — IFrame API 로드 + 플레이어 JS**

(2a) `<head>`의 htmx 스크립트 줄 아래에 IFrame API 로드 추가:
```html
<script src="https://www.youtube.com/iframe_api"></script>
```

(2b) 모달 관련 스크립트(`closeNoteModal` 정의가 있는 `</body>` 직전 `<script>` 블록)를 다음으로 보강. 기존 `closeNoteModal`에 플레이어 정리를 추가하고 플레이어 함수들을 정의:
```javascript
let ytPlayer = null;
function initYtPlayer() {
  const el = document.getElementById('yt-player');
  if (!el || !window.YT || !window.YT.Player) return;
  if (ytPlayer) { try { ytPlayer.destroy(); } catch (e) {} ytPlayer = null; }
  ytPlayer = new YT.Player('yt-player', {
    width: '100%', height: '100%',
    videoId: el.dataset.videoId,
    playerVars: { rel: 0 },
  });
}
function ytSeek(sec) {
  if (ytPlayer && ytPlayer.seekTo) { ytPlayer.seekTo(sec, true); ytPlayer.playVideo(); }
}
// API가 늦게 준비될 때를 대비
window.onYouTubeIframeAPIReady = function () { window._ytApiReady = true; initYtPlayer(); };
// 모달이 HTMX로 주입/교체될 때마다 플레이어 (재)생성
document.body.addEventListener('htmx:afterSwap', function (e) {
  if (e.target && e.target.id === 'note-modal') initYtPlayer();
});
function closeNoteModal() {
  if (ytPlayer) { try { ytPlayer.destroy(); } catch (e) {} ytPlayer = null; }
  document.getElementById('note-modal').innerHTML = '';
}
```
기존 `closeNoteModal` 정의가 이미 있으므로 **중복 정의하지 말고** 위 내용으로 교체(플레이어 정리 포함). 기존 Esc 키 핸들러(`document.addEventListener('keydown'...)`)는 그대로 둔다.

- [ ] **Step 3: 서버 렌더 sanity 체크**

```bash
python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print('detail', c.get('/api/items/1/detail').status_code)"
```
200이면 모달 템플릿이 렌더된다(노트가 없으면 빈 모달이라도 200). Jinja 에러가 없는지 확인.

- [ ] **Step 4: 브라우저 수동 검증**

```
# 전체 python 종료 후 단일 서버
python -m uvicorn main:app --reload --port 8000
```
`http://localhost:8000`에서:
1. YouTube 노트의 "전체 보기" → 모달 상단에 영상 임베드 표시, 재생되는지.
2. 타임라인이 있는 노트: 챕터 목록 표시, 챕터 클릭 시 영상이 해당 지점으로 이동(재로딩 없이).
3. 타임라인 없는 기존 YouTube 노트: "타임라인 생성" 버튼 → 클릭 → 잠시 후 모달이 챕터 목록으로 갱신.
4. 모달 닫기 → 다시 다른 노트 열기 → 플레이어가 새 영상으로 정상 재생(이전 플레이어 잔존/중복 없음).
5. 비 YouTube 노트(PDF/Code/Text) 모달: 영상 섹션 없음(회귀 없음).

- [ ] **Step 5: 전체 테스트 + 커밋**
```bash
python -m pytest -q
git add templates/partials/note_detail_modal.html templates/base.html
git commit -m "feat: modal video embed, chapter timeline, IFrame player seek"
```

---

## 최종 검증 (전체 작업 후)

- [ ] `python -m pytest -q` — 새 실패 없음(기존 3건만).
- [ ] 신규 YouTube 분석 → 타임라인 자동 생성(네이티브 있으면 무료, 없으면 AI).
- [ ] 모달에서 영상 임베드 + 챕터 클릭 이동 정상.
- [ ] 기존 노트 "타임라인 생성" 백필 정상.
- [ ] DB `items.timeline` ↔ 모달 표시 일치, 비용 기록 확인.
- [ ] 기존 기능(요약/대기열/프로젝트/태그/다크모드) 회귀 없음.
