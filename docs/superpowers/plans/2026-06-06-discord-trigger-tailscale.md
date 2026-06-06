# Discord 트리거 + Tailscale 외부 분석/열람 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공개 인터넷 노출 없이, 폰에서 Discord로 유튜브 링크/텍스트를 던지면 집 PC의 liby가 분석해 요약을 Discord로 회신하고, 전체 노트는 Tailscale 사설망으로 열람한다.

**Architecture:** Discord 봇은 아웃바운드 연결만 하며 `main.py` lifespan에서 in-process asyncio task로 기동된다. 봇과 신규 `/api/bot/*` JSON 라우터는 공유 코어 `services/bot_core.py`(분석 트리거 + 결과 조립)를 함께 호출해 DRY를 지킨다. 분석은 기존 task 큐·builder를 그대로 재사용하며, 일관성을 위해 `routers/text.py`를 youtube와 동일한 builder 패턴으로 리팩터한다. 결과 포맷은 discord 의존이 없는 순수 함수로 분리해 단위 테스트한다.

**Tech Stack:** FastAPI, discord.py, httpx(테스트), aiosqlite, pytest/pytest-asyncio. Tailscale(운영, 코드 아님).

---

## File Structure

- `config.py` (modify) — 환경변수 4개 추가.
- `requirements.txt` (modify) — `discord.py` 추가.
- `routers/text.py` (modify) — builder 패턴으로 리팩터(`_build_text_do_work` + `register_builder("text", ...)`).
- `services/discord_format.py` (create) — 노트 dict → 임베드 dict 변환 순수 함수.
- `services/bot_core.py` (create) — `submit_analysis`, `note_payload`. 봇·라우터 공유 로직.
- `routers/bot.py` (create) — `/api/bot/*` JSON 엔드포인트(코어의 얇은 래퍼 + 토큰 가드).
- `services/discord_bot.py` (create) — `handle_message`(테스트 가능 디스패치) + `start_bot`(discord.Client 배선).
- `main.py` (modify) — bot 라우터 등록 + lifespan에서 `start_bot()` 기동.
- `docs/operations-discord-tailscale.md` (create) — Tailscale·실행 운영 문서.
- 테스트: `tests/test_discord_format.py`, `tests/test_bot_core.py`, `tests/test_routes_bot.py`, `tests/test_discord_bot.py` (create), `tests/test_routes_provider_routing.py` (modify).

---

### Task 1: 설정 + 의존성

**Files:**
- Modify: `config.py:11-16` (BRIDGE_* 블록 아래에 추가)
- Modify: `requirements.txt`

- [ ] **Step 1: requirements에 discord.py 추가**

`requirements.txt` 마지막 줄(`pytest-mock==3.14.0`) 다음에 추가:

```
discord.py>=2.4,<3
```

- [ ] **Step 2: 설치**

Run: `python -m pip install "discord.py>=2.4,<3"`
Expected: `Successfully installed discord.py-2.x ...`

- [ ] **Step 3: config.py에 환경변수 추가**

`config.py`의 `DB_PATH` 줄(`DB_PATH: str = os.getenv("DB_PATH", "./liby.db")`) 바로 다음에 추가:

```python
# Discord 봇 + 외부 열람(Tailscale). 토큰 비어 있으면 봇 비활성.
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_ALLOWED_USER_ID: str = os.getenv("DISCORD_ALLOWED_USER_ID", "")
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
BOT_API_TOKEN: str = os.getenv("BOT_API_TOKEN", "")
```

- [ ] **Step 4: import 확인**

Run: `python -c "import discord, config; print(config.PUBLIC_BASE_URL)"`
Expected: `http://127.0.0.1:8000`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.py
git commit -m "feat: Discord 봇·외부 열람용 설정과 discord.py 의존 추가"
```

---

### Task 2: text.py를 builder 패턴으로 리팩터

youtube와 동일하게 spec→do_work builder를 등록해 영구화·재시도를 얻고, 봇 코어가 `enqueue(task)`로 일관되게 쓰게 한다.

**Files:**
- Modify: `routers/text.py` (전체 교체)
- Test: `tests/test_task_queue_persistence.py` (신규 테스트 1개 추가), `tests/test_routes_provider_routing.py` (기존 테스트 갱신)

- [ ] **Step 1: 실패하는 테스트 작성 — text builder 등록·재구성**

`tests/test_task_queue_persistence.py` 끝에 추가:

```python
@pytest.mark.asyncio
async def test_text_builder_registered_and_reconstructs(_isolated):
    """routers.text import 시 'text' builder가 등록되고, spec으로 do_work를 만든다."""
    import routers.text  # noqa: F401  (import 부수효과로 register_builder 실행)
    from services.ai.base import SummaryResult
    from unittest.mock import AsyncMock, patch

    assert "text" in tq._BUILDERS
    spec = {"source_type": "text", "content": "본문 텍스트",
            "provider": "claude-cli", "mode": "quick", "project_id": None}
    do_work = tq._BUILDERS["text"](spec)

    fake = AsyncMock(return_value=SummaryResult(
        title="제목", language="ko", word_count=1, reading_time_min=1,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "x", "refs": []}], cost_usd=0.0, models_used=["claude"],
    ))
    with patch("routers.text.get_provider") as gp, \
         patch("routers.text.save_note", new_callable=AsyncMock, return_value=7), \
         patch("routers.text.record_api_cost", new_callable=AsyncMock), \
         patch("routers.text.get_db_topics") as topics:
        gp.return_value.summarize = fake
        gp.return_value.name = lambda: "claude-cli"
        topics.return_value.__aenter__.return_value = []
        topics.return_value.__aexit__.return_value = False

        class T:  # 가벼운 task 더블
            title = ""; progress = ""; note_id = None
        t = T()
        await do_work(t)
    fake.assert_awaited()
    assert t.note_id == 7
    assert t.title == "제목"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_task_queue_persistence.py::test_text_builder_registered_and_reconstructs -v`
Expected: FAIL — `KeyError: 'text'` 또는 `assert "text" in tq._BUILDERS` 실패(아직 builder 미등록).

- [ ] **Step 3: routers/text.py 전체 교체**

```python
from contextlib import asynccontextmanager
from fastapi import APIRouter, Form, Request
import aiosqlite
import config
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta, register_builder
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/text", tags=["text"])


@asynccontextmanager
async def get_db_topics():
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            cursor = await db.execute("SELECT DISTINCT topic FROM items WHERE topic IS NOT NULL")
            rows = await cursor.fetchall()
        topics = [r[0] for r in rows]
    except Exception:
        topics = []
    yield topics


def _build_text_do_work(spec: dict):
    """spec → 분석 코루틴. task_queue가 영구화·재시도 시 이 builder로 재구성한다."""
    content = spec["content"]
    provider = spec["provider"]
    mode = spec.get("mode", "quick")
    pid = spec.get("project_id")

    async def do_work(t):
        ai = get_provider(provider)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(content, "text", mode, topics)
        t.title = result.title
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="text", source_url=content[:100],
            result=result, ai_provider=ai.name(), project_id=pid,
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        t.note_id = note_id

    return do_work


register_builder("text", _build_text_do_work)


@router.post("")
async def analyze_text(
    request: Request,
    content: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    content = content.strip()
    pid = parse_project_id(project_id)
    spec = {"source_type": "text", "content": content, "provider": provider,
            "mode": mode, "project_id": pid}
    task = new_task("text", content[:40], spec=spec)
    await enqueue(task)  # coro_fn 생략 → builder 재구성, 영구화·재시도
    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
```

> 주의: 기존 `routers/text.py`는 `from routers.youtube import get_db_topics`를 썼다.
> 위에서 text 자체 `get_db_topics`를 정의했으므로 youtube import 의존이 사라진다(순환 방지).

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `python -m pytest tests/test_task_queue_persistence.py::test_text_builder_registered_and_reconstructs -v`
Expected: PASS

- [ ] **Step 5: 기존 provider routing 테스트 갱신**

`tests/test_routes_provider_routing.py`의 `test_text_route_accepts_claude_cli_provider`를
아래로 교체(이제 `enqueue(task)` 단일 인자 + builder 재구성):

```python
@pytest.mark.asyncio
async def test_text_route_accepts_claude_cli_provider():
    """POST /api/text 가 provider=claude-cli를 받아 spec을 만들고 enqueue한다.
    builder로 재구성한 do_work가 BridgeProvider.summarize를 호출하는지 확인."""
    import routers.text as text_mod
    fake_summarize = AsyncMock(return_value=SummaryResult(
        title="t", language="ko", word_count=1, reading_time_min=1,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "x", "refs": []}],
        cost_usd=0.0, models_used=["claude"],
    ))
    captured = {}
    async def fake_enqueue(task, coro_fn=None):
        captured["task"] = task

    with patch("services.ai.bridge.BridgeProvider.summarize", new=fake_summarize), \
         patch("routers.text.enqueue", new=fake_enqueue), \
         patch("routers.text.save_note", new_callable=AsyncMock, return_value=1), \
         patch("routers.text.record_api_cost", new_callable=AsyncMock), \
         patch("routers.text.get_db_topics") as mock_topics:
        mock_topics.return_value.__aenter__.return_value = []
        mock_topics.return_value.__aexit__.return_value = False
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/text", data={
                "content": "안녕하세요. 짧은 입력 텍스트입니다.",
                "provider": "claude-cli", "mode": "quick",
            })
        assert resp.status_code == 200
        # spec으로 do_work 재구성 후 직접 실행 → summarize 호출됨
        task = captured["task"]
        assert task.spec["provider"] == "claude-cli"
        do_work = text_mod._build_text_do_work(task.spec)
        t = MagicMock(); t.note_id = None
        await do_work(t)
    fake_summarize.assert_awaited()
```

- [ ] **Step 6: 두 테스트 파일 통과 확인**

Run: `python -m pytest tests/test_task_queue_persistence.py tests/test_routes_provider_routing.py -v`
Expected: 모두 PASS

- [ ] **Step 7: Commit**

```bash
git add routers/text.py tests/test_task_queue_persistence.py tests/test_routes_provider_routing.py
git commit -m "refactor: text 분석을 builder 패턴으로 — 영구화·재시도 + 봇 공유 준비"
```

---

### Task 3: discord_format 순수 포맷터

**Files:**
- Create: `services/discord_format.py`
- Test: `tests/test_discord_format.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_discord_format.py`:

```python
from services.discord_format import seconds_to_mmss, chapter_link, build_embed


def test_seconds_to_mmss_minutes_and_hours():
    assert seconds_to_mmss(0) == "0:00"
    assert seconds_to_mmss(75) == "1:15"
    assert seconds_to_mmss(3661) == "1:01:01"
    assert seconds_to_mmss(-5) == "0:00"


def test_chapter_link_uses_native_youtube_timestamp():
    link = chapter_link("abc12345678", 90, "도입")
    assert link == "[1:30 도입](https://youtu.be/abc12345678?t=90)"


def test_build_embed_youtube_full():
    note = {
        "title": "제목", "summary": "요약 본문", "type": "youtube",
        "insights": ["통찰1", "통찰2"], "tags": ["투자", "심리"],
        "video_id": "vid12345678",
        "timeline": [{"t": 0, "label": "시작"}, {"t": 120, "label": "본론"}],
        "read_url": "http://pc.ts.net:8000/api/items/5/read",
    }
    e = build_embed(note)
    assert e["title"] == "제목"
    assert e["description"] == "요약 본문"
    assert e["url"] == "http://pc.ts.net:8000/api/items/5/read"
    names = [f["name"] for f in e["fields"]]
    assert "💡 핵심" in names
    assert "⏱ 타임라인" in names
    assert "🏷 태그" in names
    # 타임라인 필드에 네이티브 타임스탬프 링크 포함
    tl = next(f["value"] for f in e["fields"] if f["name"] == "⏱ 타임라인")
    assert "https://youtu.be/vid12345678?t=120" in tl
    # 전체 노트 링크 필드
    assert any("read" in f["value"] for f in e["fields"] if f["name"] == "📖 전체 노트")


def test_build_embed_text_note_without_video_has_no_timeline():
    note = {"title": "메모", "summary": "s", "type": "text",
            "insights": [], "tags": [], "read_url": "http://x/1/read"}
    e = build_embed(note)
    names = [f["name"] for f in e["fields"]]
    assert "⏱ 타임라인" not in names


def test_build_embed_truncates_long_summary():
    note = {"title": "t", "summary": "가" * 5000, "type": "text",
            "read_url": "http://x/1/read"}
    e = build_embed(note)
    assert len(e["description"]) <= 1500
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_discord_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.discord_format'`

- [ ] **Step 3: services/discord_format.py 작성**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_discord_format.py -v`
Expected: 5개 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add services/discord_format.py tests/test_discord_format.py
git commit -m "feat: Discord 임베드 포맷터 — 네이티브 유튜브 타임스탬프 링크"
```

---

### Task 4: bot_core 공유 로직

**Files:**
- Create: `services/bot_core.py`
- Test: `tests/test_bot_core.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_bot_core.py`:

```python
import pytest
import config
from models import init_db
from services import task_queue as tq
from services import bot_core


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    db_path = str(tmp_path / "b.db")
    await init_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://pc.ts.net:8000")
    monkeypatch.setattr(config, "DEFAULT_AI_PROVIDER", "claude-cli")
    tq._reset_for_tests()
    import routers.youtube, routers.text  # noqa: F401  builder 등록
    yield db_path
    tq._reset_for_tests()


@pytest.mark.asyncio
async def test_submit_analysis_detects_youtube():
    out = await bot_core.submit_analysis("https://youtu.be/dQw4w9WgXcQ")
    assert out["kind"] == "youtube"
    task = tq.get_task(out["task_id"])
    assert task.source_type == "youtube"
    assert task.spec["url"] == "https://youtu.be/dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_submit_analysis_falls_back_to_text():
    out = await bot_core.submit_analysis("그냥 메모 텍스트입니다", mode="detailed")
    assert out["kind"] == "text"
    task = tq.get_task(out["task_id"])
    assert task.source_type == "text"
    assert task.spec["mode"] == "detailed"
    assert task.spec["content"] == "그냥 메모 텍스트입니다"


@pytest.mark.asyncio
async def test_submit_analysis_empty_raises():
    with pytest.raises(ValueError):
        await bot_core.submit_analysis("   ")


@pytest.mark.asyncio
async def test_note_payload_builds_embed_with_read_url(_isolated):
    import aiosqlite, json
    async with aiosqlite.connect(_isolated) as db:
        cur = await db.execute(
            "INSERT INTO items(type,title,summary,tags,source_url) "
            "VALUES('youtube','제목','요약',?,?)",
            (json.dumps(["투자"]), "https://youtu.be/vid12345678"),
        )
        await db.commit()
        nid = cur.lastrowid
    payload = await bot_core.note_payload(nid)
    assert payload["read_url"] == f"http://pc.ts.net:8000/api/items/{nid}/read"
    assert payload["embed"]["title"] == "제목"
    assert payload["embed"]["url"].endswith(f"/api/items/{nid}/read")


@pytest.mark.asyncio
async def test_note_payload_missing_returns_none():
    assert await bot_core.note_payload(99999) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_bot_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.bot_core'`

- [ ] **Step 3: services/bot_core.py 작성**

```python
"""Discord 봇과 /api/bot 라우터가 공유하는 분석 트리거·결과 조립 로직.
in-process 호출(봇)과 HTTP(라우터)가 같은 코드를 쓰도록 한 곳에 둔다."""
import config
from services.extractor import youtube_video_id
from services.task_queue import new_task, enqueue
from services.storage import get_note
from services.discord_format import build_embed


async def submit_analysis(input_text: str, mode: str = "quick",
                          project_id: int | None = None) -> dict:
    """입력을 유튜브/텍스트로 판별해 task를 큐에 넣는다.
    반환 {task_id, title, kind}. 빈 입력이면 ValueError."""
    text = (input_text or "").strip()
    if not text:
        raise ValueError("빈 입력입니다")
    video_id = youtube_video_id(text)
    if video_id:
        spec = {"source_type": "youtube", "url": text,
                "provider": config.DEFAULT_AI_PROVIDER, "mode": mode,
                "project_id": project_id}
        task = new_task("youtube", text, spec=spec)
        kind = "youtube"
    else:
        spec = {"source_type": "text", "content": text,
                "provider": config.DEFAULT_AI_PROVIDER, "mode": mode,
                "project_id": project_id}
        task = new_task("text", text[:40], spec=spec)
        kind = "text"
    await enqueue(task)  # coro_fn 생략 → builder 재구성, 영구화·재시도
    return {"task_id": task.id, "title": task.title, "kind": kind}


async def note_payload(note_id: int) -> dict | None:
    """노트 → 봇 임베드용 payload. 없으면 None."""
    note = await get_note(config.DB_PATH, note_id)
    if note is None:
        return None
    video_id = None
    if note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    note["video_id"] = video_id
    note["read_url"] = f"{config.PUBLIC_BASE_URL}/api/items/{note_id}/read"
    return {
        "id": note_id,
        "title": note.get("title"),
        "read_url": note["read_url"],
        "embed": build_embed(note),
    }
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_bot_core.py -v`
Expected: 5개 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add services/bot_core.py tests/test_bot_core.py
git commit -m "feat: bot_core — 봇·라우터 공유 분석 트리거/결과 조립"
```

---

### Task 5: /api/bot/* JSON 라우터

**Files:**
- Create: `routers/bot.py`
- Modify: `main.py:27-36` (라우터 import·등록)
- Test: `tests/test_routes_bot.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_routes_bot.py`:

```python
import json
import pytest
import aiosqlite
import config
from httpx import AsyncClient, ASGITransport
from main import app
from models import init_db
from services import task_queue as tq


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://pc.ts.net:8000")
    monkeypatch.setattr(config, "BOT_API_TOKEN", "")
    tq._reset_for_tests()
    import routers.youtube, routers.text  # noqa: F401
    yield db_path
    tq._reset_for_tests()


@pytest.mark.asyncio
async def test_analyze_youtube_returns_task_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "https://youtu.be/dQw4w9WgXcQ"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "youtube"
    assert tq.get_task(body["task_id"]).source_type == "youtube"


@pytest.mark.asyncio
async def test_analyze_empty_input_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_task_status_json():
    out = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        out = (await c.post("/api/bot/analyze", json={"input": "메모"})).json()
        resp = await c.get(f"/api/bot/tasks/{out['task_id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("queued", "running", "done", "error")


@pytest.mark.asyncio
async def test_task_status_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/bot/tasks/deadbeef")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_note_json_includes_embed_and_read_url(_isolated):
    async with aiosqlite.connect(_isolated) as db:
        cur = await db.execute(
            "INSERT INTO items(type,title,summary,source_url) "
            "VALUES('youtube','제목','요약','https://youtu.be/vid12345678')",
        )
        await db.commit()
        nid = cur.lastrowid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/bot/notes/{nid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["read_url"].endswith(f"/api/items/{nid}/read")
    assert body["embed"]["title"] == "제목"


@pytest.mark.asyncio
async def test_token_guard_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(config, "BOT_API_TOKEN", "secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/bot/analyze", json={"input": "메모"})
    assert resp.status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.post("/api/bot/analyze", json={"input": "메모"},
                          headers={"X-Bot-Token": "secret"})
    assert ok.status_code == 200
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_bot.py -v`
Expected: FAIL — `404` 전부(라우터 미등록).

- [ ] **Step 3: routers/bot.py 작성**

```python
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import config
from services.task_queue import get_task
from services import bot_core

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _check_token(x_bot_token: str | None) -> None:
    if config.BOT_API_TOKEN and x_bot_token != config.BOT_API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid bot token")


class AnalyzeIn(BaseModel):
    input: str
    mode: str = "quick"
    project_id: int | None = None


@router.post("/analyze")
async def bot_analyze(body: AnalyzeIn, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    try:
        return await bot_core.submit_analysis(body.input, mode=body.mode, project_id=body.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks/{task_id}")
async def bot_task(task_id: str, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"status": task.status, "note_id": task.note_id,
            "error": task.error, "title": task.title}


@router.get("/notes/{note_id}")
async def bot_note(note_id: int, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    payload = await bot_core.note_payload(note_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="note not found")
    return payload
```

- [ ] **Step 4: main.py에 라우터 등록**

`main.py:27`의 import 줄에 `bot` 추가:

```python
from routers import youtube, pdf, items, settings, code, tasks, text, projects, markdown, bot
```

그리고 `app.include_router(markdown.router)` 다음 줄에 추가:

```python
app.include_router(bot.router)
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_routes_bot.py -v`
Expected: 6개 모두 PASS

- [ ] **Step 6: Commit**

```bash
git add routers/bot.py main.py tests/test_routes_bot.py
git commit -m "feat: /api/bot/* JSON 라우터 — analyze·task·note (토큰 가드)"
```

---

### Task 6: Discord 봇 핸들러 + 배선

**Files:**
- Create: `services/discord_bot.py`
- Test: `tests/test_discord_bot.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_discord_bot.py` — `handle_message`를 discord 없이 fake로 검증:

```python
import pytest
import config
from services import discord_bot as db


@pytest.fixture(autouse=True)
def _allow(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_ALLOWED_USER_ID", "111")


class Recorder:
    def __init__(self):
        self.calls = []
    async def __call__(self, text=None, embed=None):
        self.calls.append({"text": text, "embed": embed})


@pytest.mark.asyncio
async def test_ignores_other_users(monkeypatch):
    called = {"n": 0}
    async def fake_submit(*a, **k):
        called["n"] += 1
        return {"task_id": "x", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    rec = Recorder()
    await db.handle_message(999, "메모", rec)   # 허용 ID 아님
    assert called["n"] == 0
    assert rec.calls == []


@pytest.mark.asyncio
async def test_ignores_bot_messages(monkeypatch):
    rec = Recorder()
    await db.handle_message(111, "메모", rec, is_bot=True)
    assert rec.calls == []


@pytest.mark.asyncio
async def test_happy_path_done_replies_embed(monkeypatch):
    async def fake_submit(text, mode="quick", project_id=None):
        assert mode == "quick"
        return {"task_id": "tid", "title": "t", "kind": "youtube"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)

    class FakeTask:
        status = "done"; note_id = 5; error = None
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())

    async def fake_payload(nid):
        assert nid == 5
        return {"embed": {"title": "제목"}, "read_url": "http://x/5/read"}
    monkeypatch.setattr(db.bot_core, "note_payload", fake_payload)

    rec = Recorder()
    await db.handle_message(111, "https://youtu.be/dQw4w9WgXcQ", rec)
    # 첫 회신은 시작 알림, 마지막 회신은 embed 포함
    assert any(c["embed"] for c in rec.calls)
    assert rec.calls[-1]["embed"]["title"] == "제목"


@pytest.mark.asyncio
async def test_detailed_keyword_prefix(monkeypatch):
    seen = {}
    async def fake_submit(text, mode="quick", project_id=None):
        seen["mode"] = mode; seen["text"] = text
        return {"task_id": "tid", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    class FakeTask:
        status = "error"; note_id = None; error = "x"
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())
    rec = Recorder()
    await db.handle_message(111, "상세 https://youtu.be/dQw4w9WgXcQ", rec)
    assert seen["mode"] == "detailed"
    assert seen["text"] == "https://youtu.be/dQw4w9WgXcQ"  # 키워드 제거됨


@pytest.mark.asyncio
async def test_error_status_replies_failure(monkeypatch):
    async def fake_submit(*a, **k):
        return {"task_id": "tid", "title": "t", "kind": "text"}
    monkeypatch.setattr(db.bot_core, "submit_analysis", fake_submit)
    class FakeTask:
        status = "error"; note_id = None; error = "분석 폭발"
    monkeypatch.setattr(db, "get_task", lambda tid: FakeTask())
    rec = Recorder()
    await db.handle_message(111, "메모", rec)
    assert any("분석 폭발" in (c["text"] or "") for c in rec.calls)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_discord_bot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.discord_bot'`

- [ ] **Step 3: services/discord_bot.py 작성**

```python
"""Discord 봇. 메시지 디스패치(handle_message)는 discord 의존 없이 테스트 가능하게
분리하고, start_bot에서만 discord.Client를 배선한다."""
import asyncio
import logging

import config
from services.task_queue import get_task
from services import bot_core

log = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0
_POLL_MAX_TICKS = 300  # 약 10분 (2초 * 300)
_DETAIL_KEYWORDS = ("상세", "/detailed", "detailed")


def _is_authorized(author_id) -> bool:
    allowed = config.DISCORD_ALLOWED_USER_ID
    return bool(allowed) and str(author_id) == str(allowed)


def _parse_mode(text: str) -> tuple[str, str]:
    """선두 키워드로 모드 판별. 반환 (mode, 키워드 제거된 텍스트)."""
    for kw in _DETAIL_KEYWORDS:
        if text.lower().startswith(kw):
            return "detailed", text[len(kw):].strip() or text
    return "quick", text


async def _await_result(task_id: str, sleep=asyncio.sleep) -> dict:
    for _ in range(_POLL_MAX_TICKS):
        task = get_task(task_id)
        if task is None:
            return {"status": "error", "error": "task가 사라졌습니다"}
        if task.status in ("done", "error", "cancelled"):
            return {"status": task.status, "note_id": task.note_id, "error": task.error}
        await sleep(_POLL_INTERVAL)
    return {"status": "timeout", "error": "분석 시간 초과"}


async def handle_message(author_id, content: str, reply, is_bot: bool = False) -> None:
    """메시지 1건 처리. reply(text=None, embed=None)는 비동기 콜백."""
    if is_bot or not _is_authorized(author_id):
        return
    text = (content or "").strip()
    if not text:
        return
    mode, cleaned = _parse_mode(text)
    try:
        sub = await bot_core.submit_analysis(cleaned, mode=mode)
    except ValueError as e:
        await reply(text=f"⚠️ {e}")
        return
    await reply(text=f"⏳ 분석 시작… ({sub['kind']}, {mode})")
    res = await _await_result(sub["task_id"])
    if res["status"] == "done" and res.get("note_id"):
        payload = await bot_core.note_payload(res["note_id"])
        if payload:
            await reply(text="✅ 완료", embed=payload["embed"])
        else:
            await reply(text="완료했지만 노트를 찾지 못했습니다.")
    elif res["status"] == "timeout":
        await reply(text=f"⏱ {res['error']} (task {sub['task_id']})")
    else:
        await reply(text=f"❌ 분석 실패: {res.get('error') or res['status']}")


def _to_embed(embed_dict: dict):
    """포맷터의 dict → discord.Embed."""
    import discord
    e = discord.Embed(
        title=embed_dict.get("title"),
        description=embed_dict.get("description"),
        url=embed_dict.get("url"),
    )
    for f in embed_dict.get("fields", []):
        e.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
    return e


async def start_bot() -> None:
    """DISCORD_BOT_TOKEN이 있을 때만 기동. main.py lifespan에서 호출."""
    token = config.DISCORD_BOT_TOKEN
    if not token:
        log.info("DISCORD_BOT_TOKEN 미설정 — Discord 봇 비활성")
        return
    import discord
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Discord 봇 로그인: %s", client.user)

    @client.event
    async def on_message(message):
        async def reply(text=None, embed=None):
            await message.channel.send(
                content=text, embed=_to_embed(embed) if embed else None)
        await handle_message(message.author.id, message.content, reply,
                             is_bot=message.author.bot)

    try:
        await client.start(token)
    except Exception:
        log.exception("Discord 봇 비정상 종료")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_discord_bot.py -v`
Expected: 5개 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add services/discord_bot.py tests/test_discord_bot.py
git commit -m "feat: Discord 봇 핸들러 — 권한 필터·모드 키워드·폴링·임베드 회신"
```

---

### Task 7: lifespan 기동 + 운영 문서

**Files:**
- Modify: `main.py:13-23` (lifespan)
- Create: `docs/operations-discord-tailscale.md`

- [ ] **Step 1: main.py lifespan에서 봇 기동**

`main.py` 상단 import에 추가(기존 `from services.task_queue import ...` 아래):

```python
from services.discord_bot import start_bot
```

`lifespan` 함수에서 `asyncio.create_task(run_worker())` 다음 줄에 추가:

```python
    asyncio.create_task(start_bot())  # 토큰 없으면 즉시 no-op
```

- [ ] **Step 2: 서버 기동 회귀 확인(봇 토큰 없이도 정상 부팅)**

Run: `python -c "import main; print('app loads')"`
Expected: `app loads` (DISCORD_BOT_TOKEN 미설정 → 봇 no-op, import 에러 없음)

- [ ] **Step 3: 운영 문서 작성**

`docs/operations-discord-tailscale.md`:

````markdown
# 외부 분석/열람 운영 가이드 (Discord + Tailscale)

공개 인터넷 노출 없이, 폰에서 분석을 트리거하고 결과를 본다.
집 PC가 켜져 있어야 한다(분석은 로컬 Docker bridge에서만 동작).

## 1. Discord 봇 만들기

1. https://discord.com/developers/applications → New Application.
2. Bot 탭 → Add Bot → **Reset Token** 으로 토큰 복사.
3. Bot 탭에서 **Message Content Intent** 활성화(필수 — 메시지 본문 수신).
4. OAuth2 → URL Generator → scopes `bot`, 권한 `Send Messages`/`Read Message History`
   선택 → 생성된 URL로 내 개인 서버에 봇 초대(또는 봇과 DM 가능 상태로 둠).
5. 내 Discord 사용자 ID 확인: 설정 → 고급 → 개발자 모드 ON → 내 프로필 우클릭
   "사용자 ID 복사".

## 2. .env 설정

```
DISCORD_BOT_TOKEN=<봇 토큰>
DISCORD_ALLOWED_USER_ID=<내 사용자 ID>
PUBLIC_BASE_URL=http://<PC-MagicDNS-이름>.ts.net:8000
# 선택: 내부 API 추가 보호
BOT_API_TOKEN=<임의 문자열>
```

`PUBLIC_BASE_URL`은 Tailscale을 켠 뒤 4단계에서 확정한다.

## 3. 서버 실행 (한 번에 전부)

봇은 in-process라 uvicorn 한 번이면 서버 + 워커 + 봇이 함께 뜬다.
타이넷/LAN 기기가 웹 UI에 닿도록 `0.0.0.0`에 바인딩한다(이것만으로는 공개 아님 —
Tailscale/LAN 안에서만 도달).

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

선택: 위 명령을 `start.ps1`로 저장하고 Windows 작업 스케줄러 "로그온 시 실행"에
등록하면 재부팅 후 자동 기동.

## 4. Tailscale (사설망 — 전체 노트 열람용)

1. PC와 폰에 Tailscale 설치, 같은 계정으로 로그인(`tailscale up`).
2. PC의 MagicDNS 이름 확인: `tailscale status` 또는 관리 콘솔.
3. `.env`의 `PUBLIC_BASE_URL`을 `http://<그 이름>:8000`으로 설정하고 서버 재시작.
4. 폰에서 Tailscale ON → 임베드의 "전체 노트" 링크가 read.html로 열린다.

> Tailscale은 **내 기기끼리만** 연결되는 사설 메시 VPN이다. 인터넷에 공개되지 않으며
> 별도 인증 레이어가 필요 없다. Cloudflare 퍼블릭 터널과 다른 점이 이것.

## 5. 사용

- 봇에게(또는 봇이 있는 비공개 채널에) 유튜브 링크를 보낸다 → ⏳ → 잠시 후 요약 임베드.
- 임베드 타임라인의 시간 링크를 누르면 폰 유튜브 앱이 해당 지점으로 점프.
- "전체 노트" 링크(Tailscale ON)로 브라우저에서 전체 노트 열람.
- 상세 분석: 메시지를 `상세 <링크>`로 시작.
- 일반 텍스트/메모도 그대로 보내면 text 노트로 분석된다.
- 허용 ID(`DISCORD_ALLOWED_USER_ID`)가 아닌 계정의 메시지는 무시된다.
````

- [ ] **Step 4: 전체 테스트 스위트 통과 확인**

Run: `python -m pytest -q`
Expected: 모든 테스트 PASS (기존 + 신규). 실패 0.

- [ ] **Step 5: Commit**

```bash
git add main.py docs/operations-discord-tailscale.md
git commit -m "feat: lifespan에서 Discord 봇 기동 + 외부 분석/열람 운영 문서"
```

---

## Self-Review 결과

**Spec coverage:**
- 목표1(외부 트리거) → Task 4·6. 목표2(요약 회신) → Task 3·6. 목표3(Tailscale 전체 노트) → Task 4·7(read_url·문서). 목표4(공개 0·단일 실행) → Task 7(lifespan·문서).
- 구성요소 A(봇 JSON API) → Task 5. B(봇) → Task 6. C(포맷터) → Task 3. D(Tailscale) → Task 7. text builder 선행 작업 → Task 2.
- 설정 4개 → Task 1. 에러 처리(401/400/404/타임아웃/실패) → Task 5·6 테스트로 커버.

**Placeholder scan:** 모든 코드/테스트 블록은 실제 구현. TBD/TODO 없음.

**Type consistency:** `submit_analysis(input_text, mode, project_id)→{task_id,title,kind}`,
`note_payload(note_id)→{id,title,read_url,embed}|None`, `build_embed(note)→{title,description,url,fields}`,
`handle_message(author_id, content, reply, is_bot)`, `reply(text=None, embed=None)` —
Task 3~6에서 일관 사용 확인. `_BUILDERS`·`get_task`·`new_task`·`enqueue`는 기존 task_queue 시그니처와 일치.

## 비목표 (이 계획에서 안 함)
PDF·코드 파일 첨부 분석 / 공개 인터넷 노출·Cloudflare / 다중 사용자·공유 /
Discord에서 취소·재분석 / 슬래시 커맨드 등록.
