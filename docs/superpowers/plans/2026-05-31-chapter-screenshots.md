# YouTube 챕터별 영상 스크린샷 캡처 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YouTube 노트 분석 시 각 챕터 시작 시각의 영상 프레임을 jpg로 추출해 vault에 저장하고, 모달에 "📷 스크린샷 보기" 토글로 2열 그리드 노출.

**Architecture:** `services/capture.py` 신규 — 챕터별로 `yt-dlp download_ranges`로 1~2초 슬라이스 다운 + `ffmpeg`로 첫 프레임 jpg 추출 → chapter dict에 `image` 키 추가. `analyze_youtube` do_work에서 `resolve_chapters` 직후 호출. vault 디렉토리는 `main.py`에 StaticFiles로 `/vault`에 마운트해 `<img src="/vault/youtube/<slug>/ch-N.jpg">`로 서빙. 모달 템플릿에 토글 + 그리드 마크업 추가.

**Tech Stack:** FastAPI + HTMX + Jinja2 + Tailwind, SQLite(aiosqlite), yt-dlp(기존 의존), subprocess+ffmpeg(시스템 PATH), starlette StaticFiles(FastAPI 내장). 브랜치: `feature/chapter-screenshots-2026-05-31`.

---

## File Structure

**Create:**
- `services/capture.py` — `capture_chapter_screenshots` + 내부 동기 헬퍼.
- `tests/test_capture.py` — 4개 단위 테스트.

**Modify:**
- `routers/youtube.py` — `analyze_youtube` do_work에 캡처 단계 삽입.
- `main.py` — StaticFiles `/vault` 마운트.
- `templates/partials/note_detail_modal.html` — 챕터 섹션 끝에 토글+그리드 추가.
- `tests/test_routes_youtube.py` — 신규 통합 테스트 1개.
- `tests/test_routes_items.py` — 신규 모달 회귀 테스트 2개.
- `tests/test_routes_partials.py` — 신규 정적 라우트 테스트 1개.

기존 118 테스트 → 126으로 증가 예상 (+8).

---

## Task 1: `services/capture.py` (+ 단위 테스트 4개)

**Files:**
- Create: `services/capture.py`
- Create: `tests/test_capture.py`

- [ ] **Step 1: 실패 테스트 4개 작성** — `tests/test_capture.py`

```python
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
    # 디렉토리도 만들어졌는지
    assert (tmp_path / "youtube" / "myslug").is_dir()


@pytest.mark.asyncio
async def test_capture_skips_failed_chapter_continues_others(tmp_path):
    chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}, {"t": 180, "label": "C"}]
    with patch("services.capture._capture_one_sync", side_effect=[True, False, True]):
        result = await capture_chapter_screenshots(
            "https://youtu.be/x", chapters, str(tmp_path), "s")
    assert "image" in result[0]
    assert "image" not in result[1]  # 실패한 챕터는 키 없음
    assert "image" in result[2]


@pytest.mark.asyncio
async def test_capture_returns_chapters_without_images_when_all_fail(tmp_path):
    """ffmpeg 미설치/네트워크 오류 등으로 모든 캡처가 실패해도 chapters는 그대로 반환."""
    chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}]
    with patch("services.capture._capture_one_sync", return_value=False):
        result = await capture_chapter_screenshots(
            "https://youtu.be/x", chapters, str(tmp_path), "s")
    assert all("image" not in ch for ch in result)
    # 원본 키는 보존
    assert result[0]["t"] == 0 and result[0]["label"] == "A"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_capture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.capture'`.

- [ ] **Step 3: `services/capture.py` 생성**

```python
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import yt_dlp

log = logging.getLogger(__name__)

_no_ffmpeg_warned = False


def _capture_one_sync(url: str, t: int, out_jpg: str) -> bool:
    """단일 챕터 시각 t의 영상 프레임을 out_jpg로 저장. 성공 시 True.
    yt-dlp로 [t, t+2] 슬라이스만 다운 후 ffmpeg로 첫 프레임 추출."""
    global _no_ffmpeg_warned
    tmp_dir = tempfile.mkdtemp(prefix="liby-cap-")
    tmp_template = os.path.join(tmp_dir, "slice.%(ext)s")
    try:
        ydl_opts = {
            "format": "best[height<=720]/best",
            "outtmpl": tmp_template,
            "download_ranges": yt_dlp.utils.download_range_func(None, [(t, t + 2)]),
            "force_keyframes_at_cuts": False,
            "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        files = os.listdir(tmp_dir)
        if not files:
            return False
        tmp_video = os.path.join(tmp_dir, files[0])
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", "0", "-i", tmp_video, "-frames:v", "1", "-q:v", "5", out_jpg],
            timeout=30, capture_output=True,
        )
        return result.returncode == 0 and os.path.exists(out_jpg)
    except FileNotFoundError:
        if not _no_ffmpeg_warned:
            log.warning("ffmpeg not found in PATH — chapter screenshots disabled")
            _no_ffmpeg_warned = True
        return False
    except Exception as e:
        log.warning(f"capture failed at t={t}: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def capture_chapter_screenshots(
    url: str,
    chapters: list[dict],
    vault_path: str,
    note_slug: str,
) -> list[dict]:
    """각 챕터 시작 시각의 영상 프레임을 vault/youtube/<note_slug>/ch-N.jpg로 저장.
    실패한 챕터는 image 키 없이 반환(부분 성공). 빈 chapters는 그대로 반환."""
    if not chapters:
        return chapters
    out_dir = os.path.join(vault_path, "youtube", note_slug)
    os.makedirs(out_dir, exist_ok=True)
    loop = asyncio.get_running_loop()

    out_chapters = []
    for i, ch in enumerate(chapters, start=1):
        out_jpg = os.path.join(out_dir, f"ch-{i}.jpg")
        ok = await loop.run_in_executor(None, _capture_one_sync, url, ch["t"], out_jpg)
        new_ch = dict(ch)
        if ok:
            new_ch["image"] = f"{note_slug}/ch-{i}.jpg"
        out_chapters.append(new_ch)
    return out_chapters
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_capture.py -v`
Expected: 4 passed.

- [ ] **Step 5: 전체 회귀 확인 + 커밋**

Run: `python -m pytest -q`
Expected: 122 passed (118 existing + 4 new).

```bash
git add services/capture.py tests/test_capture.py
git commit -m "feat: services/capture - per-chapter video frame extraction

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `routers/youtube.py` — capture 단계 통합

**Files:**
- Modify: `routers/youtube.py`
- Test: `tests/test_routes_youtube.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_routes_youtube.py` 맨 아래에 append

```python
@pytest.mark.asyncio
async def test_youtube_pipes_chapters_with_images_to_save_note():
    """capture_chapter_screenshots이 추가한 image 키가 save_note의 timeline kwarg에 그대로 전달."""
    captured = {}
    async def fake_enqueue(task, fn): captured["fn"] = fn
    fake_ai = AsyncMock(); fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="제목", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        paragraphs=[], cost_usd=0.0, models_used=["m"])

    captured_chapters = [{"t": 0, "label": "A"}, {"t": 90, "label": "B"}]
    async def fake_capture(url, chapters, vault_path, note_slug):
        return [{**ch, "image": f"제목/ch-{i+1}.jpg"} for i, ch in enumerate(chapters)]

    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.youtube_title", new_callable=AsyncMock, return_value="제목"), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "안녕"}]}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock,
               return_value=(captured_chapters, 0.0, "")), \
         patch("routers.youtube.capture_chapter_screenshots", new=fake_capture):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc",
                                               "provider": "claude", "mode": "quick"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    timeline_arg = mock_save.call_args.kwargs["timeline"]
    assert timeline_arg == [
        {"t": 0, "label": "A", "image": "제목/ch-1.jpg"},
        {"t": 90, "label": "B", "image": "제목/ch-2.jpg"},
    ]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_youtube.py -k pipes_chapters_with_images -v`
Expected: FAIL — `capture_chapter_screenshots` not imported in routers.youtube.

- [ ] **Step 3a: import 추가** — `routers/youtube.py` 상단 import 블록

기존 라인 5-9:
```python
from services.extractor import extract_youtube_full, segments_to_transcript, youtube_title
from services.chapters import resolve_chapters
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta
```
추가(맨 아래에 `capture` 한 줄, `_safe_filename` 추가):
```python
from services.extractor import extract_youtube_full, segments_to_transcript, youtube_title
from services.chapters import resolve_chapters
from services.ai import get_provider
from services.storage import save_note, record_api_cost, _safe_filename
from services.task_queue import new_task, enqueue, queue_meta
from services.capture import capture_chapter_screenshots
```

- [ ] **Step 3b: do_work에 캡처 단계 삽입** — `routers/youtube.py` line 53-60

기존:
```python
        t.progress = "타임라인 생성 중..."
        chapters, ch_cost, ch_model = await resolve_chapters(
            data["native_chapters"], data["segments"], ai)
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
        )
```
신규(capture 단계 삽입):
```python
        t.progress = "타임라인 생성 중..."
        chapters, ch_cost, ch_model = await resolve_chapters(
            data["native_chapters"], data["segments"], ai)
        if chapters:
            t.progress = "스크린샷 캡처 중..."
            chapters = await capture_chapter_screenshots(
                url, chapters, config.VAULT_PATH, _safe_filename(result.title))
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
        )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_youtube.py -k pipes_chapters_with_images -v`
Expected: PASS.

- [ ] **Step 5: 기존 테스트 회귀 확인 + 커밋**

Run: `python -m pytest -q`
Expected: 123 passed (122 + 1 new). 기존 `test_youtube_quick_passes_timestamped_transcript_and_paragraphs` 등도 통과해야 함 — 이 테스트들은 `resolve_chapters`를 mock하므로 capture가 새로 들어와도 영향 없어야 하지만, mock 안 한 채로 fall through되면 실제 capture_chapter_screenshots가 호출돼 yt-dlp가 네트워크 시도. 만약 실패하면 기존 테스트에 `patch("routers.youtube.capture_chapter_screenshots", new=lambda u,c,v,s: c)` 같은 mock 추가 필요.

기존 테스트가 한 번에 통과하지 않으면 멈추고 BLOCKED 보고 — controller가 어떤 테스트 수정이 필요한지 결정.

```bash
git add routers/youtube.py tests/test_routes_youtube.py
git commit -m "feat: pipe chapter screenshots through analyze_youtube

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `main.py` StaticFiles `/vault` 마운트

**Files:**
- Modify: `main.py`
- Test: `tests/test_routes_partials.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_routes_partials.py` 맨 아래에 append

```python
@pytest.mark.asyncio
async def test_vault_static_mount_serves_existing_file(tmp_path):
    """/vault/<path>가 config.VAULT_PATH 하위의 실제 파일을 서빙해야 한다."""
    import config
    import pathlib
    target_dir = pathlib.Path(config.VAULT_PATH) / "youtube" / "_test_static_mount"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "ch-1.txt"
    target.write_text("hello", encoding="utf-8")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/vault/youtube/_test_static_mount/ch-1.txt")
        assert resp.status_code == 200
        assert resp.text == "hello"
    finally:
        target.unlink(missing_ok=True)
        try: target_dir.rmdir()
        except OSError: pass
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py -k vault_static_mount -v`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: `main.py` 수정 — StaticFiles import + mount**

기존 import 블록(`main.py` line 1-7):
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from models import init_db
from templates_env import templates
from services.task_queue import run_worker
```
신규 import 추가:
```python
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from models import init_db
from templates_env import templates
from services.task_queue import run_worker
import config
```

라우터 include 블록(line 17-26) 직후에 마운트 추가:
```python
from routers import youtube, pdf, items, settings, code, tasks, text, projects, markdown
app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)
app.include_router(code.router)
app.include_router(tasks.router)
app.include_router(text.router)
app.include_router(projects.router)
app.include_router(markdown.router)

os.makedirs(config.VAULT_PATH, exist_ok=True)
app.mount("/vault", StaticFiles(directory=config.VAULT_PATH), name="vault")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -k vault_static_mount -v`
Expected: PASS.

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `python -m pytest -q`
Expected: 124 passed (123 + 1 new).

```bash
git add main.py tests/test_routes_partials.py
git commit -m "feat: mount /vault as StaticFiles for chapter screenshots

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 모달 토글 + 그리드

**Files:**
- Modify: `templates/partials/note_detail_modal.html`
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 2개 추가** — `tests/test_routes_items.py` 맨 아래에 append

```python
@pytest.mark.asyncio
async def test_modal_renders_screenshot_toggle_when_timeline_has_images():
    """timeline에 image 키가 있으면 모달이 토글 + img 마크업을 렌더."""
    note = dict(MOCK_NOTE)
    note["timeline"] = [
        {"t": 0, "label": "A", "image": "slug/ch-1.jpg"},
        {"t": 90, "label": "B", "image": "slug/ch-2.jpg"},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "📷 스크린샷 보기" in resp.text
    assert 'src="/vault/youtube/slug/ch-1.jpg"' in resp.text
    assert 'src="/vault/youtube/slug/ch-2.jpg"' in resp.text


@pytest.mark.asyncio
async def test_modal_hides_screenshot_toggle_when_no_images():
    """timeline에 image 키가 없으면 토글 마크업이 안 보여야 한다."""
    note = dict(MOCK_NOTE)
    note["timeline"] = [
        {"t": 0, "label": "A"},
        {"t": 90, "label": "B"},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "📷 스크린샷 보기" not in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_items.py -k screenshot_toggle -v`
Expected: 1 FAIL (renders), 1 PASS (hides — 토글 마크업 자체가 아직 없으므로 자연스럽게 통과).

- [ ] **Step 3: 모달 템플릿 수정** — `templates/partials/note_detail_modal.html`

라인 60(`</ul>`) 직후, 라인 61(`{% elif note.type == 'youtube' %}`) 직전에 토글 + 그리드 블록 삽입.

기존 라인 47-69:
```html
      {% set tl = note.timeline if note.timeline is not string else (note.timeline | fromjson) %}
      {% if tl %}
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">챕터</h3>
      <ul class="space-y-0.5 max-h-48 overflow-y-auto">
        {% for ch in tl %}
        <li>
          <button type="button" onclick="ytSeek({{ ch.t }})"
                  class="w-full text-left flex gap-2 text-[12px] text-gray-700 dark:text-gray-300 hover:bg-[#EAF4EE] dark:hover:bg-[#14291E] rounded px-2 py-1 transition-colors">
            <span class="text-[#1F6F4A] dark:text-[#34A66A] font-mono flex-shrink-0">{{ fmt_ts(ch.t) }}</span>
            <span class="truncate">{{ ch.label }}</span>
          </button>
        </li>
        {% endfor %}
      </ul>
      {% elif note.type == 'youtube' %}
      <button hx-post="/api/items/{{ note.id }}/timeline"
              hx-target="#note-modal" hx-swap="innerHTML"
              hx-indicator="#timeline-spinner" hx-disabled-elt="this"
              class="text-xs bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] border border-[#A8CBB2] dark:border-[#2D6B4A] rounded-lg px-3 py-1.5 font-semibold hover:bg-[#1F6F4A] hover:text-white transition-colors disabled:opacity-50">
        ⏱ 타임라인 생성
      </button>
      <span id="timeline-spinner" class="htmx-indicator text-[11px] text-gray-400 ml-2">생성 중...</span>
      {% endif %}
```
신규(`{% if tl %}` 블록 안 `</ul>` 직후에 토글 삽입):
```html
      {% set tl = note.timeline if note.timeline is not string else (note.timeline | fromjson) %}
      {% if tl %}
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">챕터</h3>
      <ul class="space-y-0.5 max-h-48 overflow-y-auto">
        {% for ch in tl %}
        <li>
          <button type="button" onclick="ytSeek({{ ch.t }})"
                  class="w-full text-left flex gap-2 text-[12px] text-gray-700 dark:text-gray-300 hover:bg-[#EAF4EE] dark:hover:bg-[#14291E] rounded px-2 py-1 transition-colors">
            <span class="text-[#1F6F4A] dark:text-[#34A66A] font-mono flex-shrink-0">{{ fmt_ts(ch.t) }}</span>
            <span class="truncate">{{ ch.label }}</span>
          </button>
        </li>
        {% endfor %}
      </ul>
      {% set has_images = tl | selectattr('image', 'defined') | list | length > 0 %}
      {% if has_images %}
      <details class="mt-3">
        <summary class="cursor-pointer text-[11px] font-bold text-[#1F6F4A] dark:text-[#34A66A] hover:underline select-none">📷 스크린샷 보기</summary>
        <div class="grid grid-cols-2 gap-3 mt-3">
          {% for ch in tl %}
          {% if ch.image is defined %}
          <div class="text-[11px]">
            <button type="button"
                    onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ ch.t }})"
                    class="block w-full">
              <img src="/vault/youtube/{{ ch.image }}"
                   alt="{{ ch.label }}"
                   class="w-full rounded-lg border border-[#E2E8E4] dark:border-gray-700 hover:opacity-90 transition-opacity">
            </button>
            <div class="mt-1 text-gray-600 dark:text-gray-400 flex items-center gap-1">
              <span class="font-mono text-[#1F6F4A] dark:text-[#34A66A]">⏱{{ fmt_ts(ch.t) }}</span>
              <span class="truncate">{{ ch.label }}</span>
            </div>
          </div>
          {% endif %}
          {% endfor %}
        </div>
      </details>
      {% endif %}
      {% elif note.type == 'youtube' %}
      <button hx-post="/api/items/{{ note.id }}/timeline"
              hx-target="#note-modal" hx-swap="innerHTML"
              hx-indicator="#timeline-spinner" hx-disabled-elt="this"
              class="text-xs bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] border border-[#A8CBB2] dark:border-[#2D6B4A] rounded-lg px-3 py-1.5 font-semibold hover:bg-[#1F6F4A] hover:text-white transition-colors disabled:opacity-50">
        ⏱ 타임라인 생성
      </button>
      <span id="timeline-spinner" class="htmx-indicator text-[11px] text-gray-400 ml-2">생성 중...</span>
      {% endif %}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -k screenshot_toggle -v`
Expected: 2 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `python -m pytest -q`
Expected: 126 passed (124 + 2 new).

```bash
git add templates/partials/note_detail_modal.html tests/test_routes_items.py
git commit -m "feat: modal renders chapter screenshot toggle grid

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: 브라우저 E2E 검증 (수동)

**Files:** 없음 (모든 작업 통합 검증)

- [ ] **Step 1: 서버 재시작**

```bash
# 기존 uvicorn 종료 후 (PID 확인 → Stop-Process -Id <PID> -Force)
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: ffmpeg 설치 확인**

```bash
ffmpeg -version
```
Expected: 버전 출력. 없으면 winget/choco/scoop으로 설치 후 PATH 확인.

- [ ] **Step 3: 챕터가 있는 YouTube 영상 분석**

브라우저 `http://localhost:8000` → YouTube 탭 → 챕터가 3개 이상 있는 영상 URL(예: 강의·튜토리얼) → 빠른 정리. "스크린샷 캡처 중..." 진행 메시지가 잠시 보인 뒤 완료.

- [ ] **Step 4: vault 확인**

```bash
ls vault/youtube/<note-slug>/
```
Expected: `ch-1.jpg, ch-2.jpg, ...` (챕터 개수만큼). 각 파일 크기 ~50~200KB.

- [ ] **Step 5: 모달 검증**

- 카드 본문 클릭 → 모달 열림.
- 영상 임베드 + 챕터 list 아래에 `📷 스크린샷 보기` 토글 보임.
- 토글 클릭 → 2열 그리드로 모든 캡처 + 챕터 라벨/시각 노출.
- 이미지 클릭 → 영상이 해당 시각으로 점프.

- [ ] **Step 6: 옛 노트 백워드 호환 검증**

기존 YouTube 노트(image 키 없는 timeline) 열기:
- 챕터 list는 정상.
- `📷 스크린샷 보기` 토글은 안 보임(has_images = false).

- [ ] **Step 7: ffmpeg 미설치 검증 (선택)**

ffmpeg를 일시 PATH에서 제거 후 새 분석:
- "스크린샷 캡처 중..." 메시지는 보이지만 즉시 다음 단계로.
- 모달에 토글 없음, 에러 페이지 X.

검증 완료 시 Plan 종료.
