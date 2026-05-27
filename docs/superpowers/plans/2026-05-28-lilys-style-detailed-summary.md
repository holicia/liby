# Lilys 스타일 상세 요약 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세 정리(detailed) 요약을 한 줄 요약 + 목차 + 계층형 본문(굵은 소제목 + 중첩 불릿)으로 생성·렌더하고, youtube 노트는 각 항목에 타임스탬프를 붙여 임베드 영상에서 클릭 이동하게 한다.

**Architecture:** detailed일 때 tier2가 계층 `sections`(JSON)를 직접 생성(1안). youtube-detailed는 타임스탬프 자막을 요약 입력으로 줘 `t`(초)를 부여. tier3는 인사이트/질문만 생성. 모달·마크다운은 `sections`가 있으면 계층 렌더, 없으면(quick) 기존 평면.

**Tech Stack:** FastAPI + HTMX + Jinja2, SQLite(aiosqlite), Anthropic/OpenAI SDK, pytest + pytest-asyncio.

---

## 데이터 형태 (모든 태스크 공통 참조)

`SummaryResult.sections`(현재 `list[str]`, 미사용)를 다음 계층으로 재정의:

```jsonc
[ { "heading": "1. 대주제", "t": 150,            // t는 선택(youtube만)
    "subsections": [
      { "heading": "1.1 소주제", "t": 36,
        "items": [ { "lead": "굵은 소제목", "t": 36, "bullets": ["세부1", "세부2"] } ] } ] } ]
```

DB `items.sections`는 이미 JSON TEXT + `_JSON_FIELDS` 포함 → 마이그레이션 불필요. quick은 `sections=[]` 유지.

---

## Task 1: `_build_sections` 가드 헬퍼 (claude.py)

**Files:**
- Modify: `services/ai/claude.py` (`_build_chapters` 아래에 추가)
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: Write the failing test** — `tests/test_claude_provider.py` 끝에 추가

```python
def test_build_sections_hierarchy_and_timestamps():
    from services.ai.claude import _build_sections
    data = {"sections": [
        {"heading": "1. 대주제", "t": "0", "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"lead": "리드", "t": "1:30", "bullets": ["a", "b", ""]},
            ]},
        ]},
    ]}
    assert _build_sections(data) == [
        {"heading": "1. 대주제", "t": 0, "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"lead": "리드", "bullets": ["a", "b"]},  # "1:30"은 숫자 아님 → t 생략, 빈 불릿 제거
            ]},
        ]},
    ]


def test_build_sections_skips_invalid():
    from services.ai.claude import _build_sections
    data = {"sections": ["notdict", {"heading": "", "subsections": []},
                         {"heading": "1. ok", "subsections": []}]}
    assert _build_sections(data) == [{"heading": "1. ok", "subsections": []}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_claude_provider.py -k build_sections -v`
Expected: FAIL (ImportError: cannot import name `_build_sections`)

- [ ] **Step 3: Implement** — `services/ai/claude.py`, `_build_chapters` 함수 정의 바로 아래에 추가

```python
def _to_t(val) -> int | None:
    try:
        return int(float(val))  # 150, "150", 150.0 허용; "1:30" 등은 None
    except (TypeError, ValueError):
        return None


def _build_sections(data: dict) -> list[dict]:
    """LLM 응답 dict → 계층형 sections. 각 단계 가드, 잘못된 항목은 건너뜀."""
    out = []
    for sec in data.get("sections", []):
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading", "")).strip()
        if not heading:
            continue
        subs = []
        for sub in sec.get("subsections", []):
            if not isinstance(sub, dict):
                continue
            sub_heading = str(sub.get("heading", "")).strip()
            if not sub_heading:
                continue
            items = []
            for it in sub.get("items", []):
                if not isinstance(it, dict):
                    continue
                lead = str(it.get("lead", "")).strip()
                bullets = [str(b).strip() for b in it.get("bullets", []) if str(b).strip()]
                if not lead and not bullets:
                    continue
                item = {"lead": lead, "bullets": bullets}
                t = _to_t(it.get("t"))
                if t is not None:
                    item["t"] = t
                items.append(item)
            sub_obj = {"heading": sub_heading, "items": items}
            st = _to_t(sub.get("t"))
            if st is not None:
                sub_obj["t"] = st
            subs.append(sub_obj)
        sec_obj = {"heading": heading, "subsections": subs}
        sect = _to_t(sec.get("t"))
        if sect is not None:
            sec_obj["t"] = sect
        out.append(sec_obj)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_claude_provider.py -k build_sections -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: add _build_sections guard helper for hierarchical summary"
```

---

## Task 2: detailed 프롬프트 + summarize 분기 + tier3 축소 (claude.py)

**Files:**
- Modify: `services/ai/claude.py` (프롬프트 상수, `summarize`, `TIER3_PROMPT`)
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_summarize_detailed_builds_sections(provider):
    import json
    tier2 = MagicMock()
    tier2.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "summary": "한 줄 요약",
        "tags": ["x"], "suggested_topic": "AI",
        "sections": [{"heading": "1. A", "t": 0, "subsections": [
            {"heading": "1.1 B", "items": [{"lead": "L", "t": 30, "bullets": ["b1"]}]}]}],
    }, ensure_ascii=False))]
    tier2.usage = MagicMock(input_tokens=10, output_tokens=10)
    tier3 = MagicMock()
    tier3.content = [MagicMock(text=json.dumps({"insights": ["i"], "questions_raised": ["q"]}))]
    tier3.usage = MagicMock(input_tokens=5, output_tokens=5)
    with patch.object(provider._client.messages, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("[0:00] hi", "youtube", "detailed", [])
    assert res.sections[0]["heading"] == "1. A"
    assert res.sections[0]["subsections"][0]["items"][0]["t"] == 30
    assert res.insights == ["i"]
    assert res.questions_raised == ["q"]
    assert res.summary == "한 줄 요약"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_claude_provider.py::test_summarize_detailed_builds_sections -v`
Expected: FAIL (res.sections empty — detailed prompt/branch not added yet)

- [ ] **Step 3a: Add DETAILED_PROMPT** — `services/ai/claude.py`, `TIER2_CODE_PROMPT` 정의 바로 아래에 추가

```python
DETAILED_PROMPT = """다음 내용을 분석하여 상세 노트를 계층 구조로 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 5~12개의 의미 단위 대섹션(heading: "1. ...", "2. ...")으로 나눕니다.
- 각 대섹션은 1개 이상의 소섹션(heading: "1.1 ...")을 가지며, 각 소섹션은 굵게 강조할 핵심 항목(lead)과 그 아래 2~5개의 세부 불릿(bullets)을 가집니다.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있으면, 해당 섹션/소섹션/항목이 시작되는 지점의 t를 "초 단위 정수"로 채웁니다. 타임스탬프가 없으면 t는 생략합니다.

JSON으로만 응답하세요:
{{"title": "제목", "language": "ko|en",
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명",
  "sections": [
    {{"heading": "1. 대주제", "t": 0, "subsections": [
      {{"heading": "1.1 소주제", "t": 0, "items": [
        {{"lead": "굵은 소제목", "t": 0, "bullets": ["세부 1", "세부 2"]}}
      ]}}
    ]}}
  ]}}"""
```

- [ ] **Step 3b: Reduce TIER3_PROMPT** — 기존 `TIER3_PROMPT` 정의를 교체

```python
TIER3_PROMPT = """다음 요약을 바탕으로 심화 분석을 수행하세요.

요약: {summary}

JSON으로 응답하세요:
{{"insights": ["인사이트1", "인사이트2"],
  "questions_raised": ["질문1", "질문2"]}}"""
```

- [ ] **Step 3c: Branch template + build sections in `summarize`** — `services/ai/claude.py`

`summarize` 내 템플릿 선택부를 교체:
```python
        model = config.CLAUDE_MODELS["tier2"]
        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
```

그리고 `SummaryResult(...)` 생성에서 `sections=data.get("sections", [])`를 다음으로 교체:
```python
            sections=_build_sections(data),
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_claude_provider.py -v`
Expected: PASS (기존 + 신규 모두). `test_summarize_quick_*`도 통과(quick은 `_build_sections`가 `[]` 반환).

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: detailed tier2 emits hierarchical sections; trim tier3 to insights/questions"
```

---

## Task 3: OpenAI 프로바이더 미러 (openai_provider.py)

**Files:**
- Modify: `services/ai/openai_provider.py` (import, `summarize` 분기/sections)
- Test: `tests/test_openai_provider.py`

- [ ] **Step 1: Write the failing test** — `tests/test_openai_provider.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_openai_summarize_detailed_builds_sections(provider):
    import json
    from unittest.mock import AsyncMock, MagicMock, patch
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "summary": "한 줄",
        "tags": ["x"], "suggested_topic": "AI",
        "sections": [{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [{"lead": "L", "bullets": ["b1"]}]}]}],
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    tier3 = MagicMock()
    tier3.choices = [MagicMock(message=MagicMock(content=json.dumps(
        {"insights": ["i"], "questions_raised": ["q"]})))]
    tier3.usage = MagicMock(prompt_tokens=5, completion_tokens=5)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("text", "pdf", "detailed", [])
    assert res.sections[0]["subsections"][0]["items"][0]["lead"] == "L"
    assert res.insights == ["i"]
```

(`provider` fixture가 없으면 파일 상단 기존 fixture를 참고해 동일 패턴으로 추가: `OpenAIProvider(api_key="test")`.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_openai_provider.py -k detailed_builds_sections -v`
Expected: FAIL (sections empty)

- [ ] **Step 3a: Update import** — `services/ai/openai_provider.py:4`

```python
from services.ai.claude import TIER2_PROMPT, TIER2_CODE_PROMPT, TIER3_PROMPT, CHAPTERS_PROMPT, DETAILED_PROMPT, _build_chapters, _build_sections
```

- [ ] **Step 3b: Branch template + sections in `summarize`** — `services/ai/openai_provider.py`

템플릿 선택부 교체:
```python
        model = config.GPT_MODELS["tier2"]
        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
```

`SummaryResult(...)`의 `sections=data.get("sections", [])` → `sections=_build_sections(data)`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_openai_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/ai/openai_provider.py tests/test_openai_provider.py
git commit -m "feat: openai provider emits hierarchical sections in detailed mode"
```

---

## Task 4: 마크다운 계층 렌더 + upgrade가 sections 저장 (storage.py)

**Files:**
- Modify: `services/storage.py` (`_make_md_content`, `upgrade_to_detailed`)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test** — `tests/test_storage.py` 끝에 추가

```python
def test_make_md_content_hierarchical():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [{"lead": "L", "t": 90, "bullets": ["b1", "b2"]}]}]}],
        summary="한 줄", key_points=[], tags=["x"], suggested_topic="AI",
        summary_mode="detailed", insights=["i"], questions_raised=["q"])
    md = _make_md_content("youtube", "u", r, "claude")
    assert "## 목차" in md
    assert "## 1. A" in md
    assert "### 1.1 B" in md
    assert "- **L** (1:30)" in md
    assert "  - b1" in md
    assert "## 인사이트" in md
    assert "핵심 논거" not in md


def test_make_md_content_quick_stays_flat():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="요약", key_points=["k1"], tags=[], suggested_topic="",
        summary_mode="quick")
    md = _make_md_content("text", "u", r, "claude")
    assert "## 핵심 포인트" in md
    assert "## 목차" not in md
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_storage.py -k make_md_content -v`
Expected: FAIL (목차/계층 없음)

- [ ] **Step 3a: Rewrite `_make_md_content` body** — `services/storage.py`

프론트매터 생성부(`lines = [... "---", ""]`)는 유지하고, 그 이후 본문 생성 로직을 교체. 아래는 `lines`가 프론트매터 + `""`까지 채워진 직후의 본문 처리:

```python
    def _ts(sec: int) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    lines += ["## 요약", result.summary, ""]

    if result.sections:  # detailed 계층 본문
        lines.append("## 목차")
        for sec in result.sections:
            lines.append(f"- {sec['heading']}")
            for sub in sec.get("subsections", []):
                lines.append(f"  - {sub['heading']}")
        lines.append("")
        for sec in result.sections:
            lines += [f"## {sec['heading']}", ""]
            for sub in sec.get("subsections", []):
                lines += [f"### {sub['heading']}", ""]
                for it in sub.get("items", []):
                    ts = f" ({_ts(it['t'])})" if "t" in it else ""
                    lines.append(f"- **{it['lead']}**{ts}")
                    for b in it.get("bullets", []):
                        lines.append(f"  - {b}")
                lines.append("")
    else:  # quick 평면 본문
        lines.append("## 핵심 포인트")
        for p in result.key_points:
            lines.append(f"- {p}")

    if result.insights:
        lines += ["", "## 인사이트"]
        for i in result.insights:
            lines.append(f"- {i}")
    if result.questions_raised:
        lines += ["", "## 탐구할 질문"]
        for q in result.questions_raised:
            lines.append(f"- {q}")
    return "\n".join(lines)
```

기존 본문 블록(`"## 요약", result.summary, "", "## 핵심 포인트"` 및 `main_arguments`/`insights`/`questions_raised` 루프)은 위 코드로 **완전히 대체**한다. (핵심 논거 블록 삭제.)

- [ ] **Step 3b: `upgrade_to_detailed`가 sections도 저장** — `services/storage.py`

UPDATE 문에 `sections=?`를 추가하고 값에 `json.dumps(result.sections or [], ensure_ascii=False)`를 첫 파라미터로 넣는다:
```python
        await db.execute(
            """UPDATE items SET
               summary_mode='detailed',
               sections=?,
               main_arguments=?, insights=?, questions_raised=?,
               related_concepts=?, api_cost_usd=api_cost_usd+?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                json.dumps(result.sections or [], ensure_ascii=False),
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                result.cost_usd, note_id,
            )
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS (기존 + 신규 모두)

- [ ] **Step 5: Commit**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: hierarchical markdown render and persist sections on upgrade"
```

---

## Task 5: youtube 라우터 — detailed에 타임스탬프 자막 전달 (youtube.py)

**Files:**
- Modify: `routers/youtube.py` (import, `do_work`)
- Test: `tests/test_routes_youtube.py`

- [ ] **Step 1: Write the failing test** — `tests/test_routes_youtube.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_youtube_detailed_passes_timestamped_transcript():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="detailed",
        cost_usd=0.0, models_used=["m"])
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "PLAIN", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "안녕"}]}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1), \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc",
                                               "provider": "claude", "mode": "detailed"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    arg0 = fake_ai.summarize.call_args.args[0]
    assert "[0:00]" in arg0 and "안녕" in arg0  # 평문 PLAIN이 아니라 타임스탬프 자막 전달
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_routes_youtube.py -k timestamped_transcript -v`
Expected: FAIL (arg0 == "PLAIN")

- [ ] **Step 3a: Add import** — `routers/youtube.py:5` 부근

```python
from services.extractor import extract_youtube_full, segments_to_transcript
```

- [ ] **Step 3b: Choose summarize input in `do_work`** — `routers/youtube.py`

`do_work` 내 요약 호출부를 교체:
```python
        t.progress = "AI 분석 중..."
        if mode == "detailed" and data["segments"]:
            summarize_input = segments_to_transcript(data["segments"])
        else:
            summarize_input = data["text"]
        async with get_db_topics() as topics:
            result = await ai.summarize(summarize_input, "youtube", mode, topics)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_routes_youtube.py -v`
Expected: PASS (신규 + 기존 task_card 테스트 유지)

- [ ] **Step 5: Commit**

```bash
git add routers/youtube.py tests/test_routes_youtube.py
git commit -m "feat: feed timestamped transcript to detailed youtube summary"
```

---

## Task 6: 상세 정리 업그레이드 — youtube 계층 재생성 (items.py)

**Files:**
- Modify: `routers/items.py` (import, `upgrade_note` `do_work`)
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: Write the failing test** — `tests/test_routes_items.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_upgrade_youtube_regenerates_sections():
    captured = {}
    async def fake_enqueue(task, fn):
        captured["fn"] = fn
    note = {**MOCK_NOTE, "type": "youtube", "source_url": "https://youtu.be/abc", "summary": "s"}
    fake_ai = AsyncMock()
    fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    full = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": []}],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="detailed",
        insights=["i"], questions_raised=["q"], cost_usd=0.0, models_used=["m"])
    fake_ai.summarize.return_value = full
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note), \
         patch("routers.items.get_provider", return_value=fake_ai), \
         patch("routers.items.enqueue", new=fake_enqueue), \
         patch("routers.items.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "a"}]}), \
         patch("routers.items.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")), \
         patch("routers.items.set_timeline", new_callable=AsyncMock), \
         patch("routers.items.upgrade_to_detailed", new_callable=AsyncMock) as mock_up, \
         patch("routers.items.record_api_cost", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/upgrade")
        assert resp.status_code == 200
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    passed = mock_up.call_args.args[2]  # (db_path, note_id, result)
    assert passed.sections[0]["heading"] == "1. A"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_routes_items.py -k regenerates_sections -v`
Expected: FAIL (youtube 분기가 summarize를 쓰지 않아 sections 없음)

- [ ] **Step 3a: Add import** — `routers/items.py:12` 부근

```python
from services.extractor import youtube_video_id, extract_youtube_full, segments_to_transcript
```

- [ ] **Step 3b: Rewrite `do_work` in `upgrade_note`** — `routers/items.py`

기존 `do_work`(run_tier3 → upgrade_to_detailed → youtube 타임라인)를 다음으로 교체:
```python
    async def do_work(t):
        is_yt = note.get("type") == "youtube" and note.get("source_url")
        if is_yt:
            t.progress = "상세 분석 중..."
            try:
                data = await extract_youtube_full(note["source_url"])
                src = segments_to_transcript(data["segments"]) if data["segments"] else data["text"]
                full = await provider.summarize(src, "youtube", "detailed", [])
                await upgrade_to_detailed(config.DB_PATH, note_id, full)
                await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, full.cost_usd, note_id)
                t.progress = "타임라인 생성 중..."
                chapters, cost, model = await resolve_chapters(
                    data["native_chapters"], data["segments"], provider)
                await set_timeline(config.DB_PATH, note_id, chapters)
                if cost > 0:
                    await record_api_cost(config.DB_PATH, provider.name(), model, 0, 0, cost, note_id)
            except Exception:
                pass  # 자막 없음/네트워크 오류 → 상세 정리 실패해도 모달은 재렌더
        else:
            t.progress = "상세 분석 중..."
            detailed = await provider.run_tier3(note["summary"])
            await upgrade_to_detailed(config.DB_PATH, note_id, detailed)
            await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, detailed.cost_usd, note_id)
        t.note_id = note_id
```

(주의: youtube 분기는 `summarize`가 내부에서 tier3까지 수행하므로 `run_tier3`를 호출하지 않는다. `upgrade_to_detailed`는 Task 4에서 sections도 저장하도록 확장됨.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_routes_items.py -v`
Expected: PASS (신규 + 기존 upgrade/backfill 테스트 유지)

- [ ] **Step 5: Commit**

```bash
git add routers/items.py tests/test_routes_items.py
git commit -m "feat: youtube upgrade regenerates hierarchical sections"
```

---

## Task 7: 모달 계층 렌더 + 목차 + 핵심 논거 제거 (note_detail_modal.html)

**Files:**
- Modify: `templates/partials/note_detail_modal.html`
- 검증: 브라우저 수동 (단위 테스트 없음)

- [ ] **Step 1: Replace 핵심 포인트 block with conditional sections+TOC**

`note_detail_modal.html`의 `<!-- 핵심 포인트 -->` 블록(현재 `{% if note.key_points %}...{% endif %}` 전체)을 아래로 **교체**:
```html
    {% set sec_list = note.sections if note.sections is not string else (note.sections | fromjson) %}
    {% if sec_list %}
    <!-- 목차 -->
    <div class="mb-4">
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">목차</h3>
      <ul class="space-y-0.5 text-[12px]">
        {% for sec in sec_list %}
        <li><a href="#sec-{{ loop.index }}" class="text-gray-700 dark:text-gray-300 hover:text-[#1F6F4A] dark:hover:text-[#34A66A]">{{ sec.heading }}</a>
          {% if sec.subsections %}
          <ul class="ml-3 space-y-0.5">
            {% for sub in sec.subsections %}
            <li><a href="#sec-{{ loop.parent.loop.index }}-{{ loop.index }}" class="text-gray-500 dark:text-gray-400 hover:text-[#1F6F4A] dark:hover:text-[#34A66A]">{{ sub.heading }}</a></li>
            {% endfor %}
          </ul>
          {% endif %}
        </li>
        {% endfor %}
      </ul>
    </div>
    <!-- 계층 본문 -->
    <div class="mb-4 space-y-4">
      {% for sec in sec_list %}
      <div id="sec-{{ loop.index }}">
        <h2 class="text-[15px] font-bold text-[#1F2937] dark:text-gray-100 mb-2 flex items-center gap-2">
          {{ sec.heading }}
          {% if sec.t is defined and video_id %}<button type="button" onclick="ytSeek({{ sec.t }})" class="text-[11px] font-mono text-[#1F6F4A] dark:text-[#34A66A] hover:underline">⏱{{ "%d:%02d:%02d"|format(sec.t // 3600, sec.t % 3600 // 60, sec.t % 60) if sec.t >= 3600 else "%d:%02d"|format(sec.t // 60, sec.t % 60) }}</button>{% endif %}
        </h2>
        {% for sub in sec.subsections %}
        <div id="sec-{{ loop.parent.loop.index }}-{{ loop.index }}" class="mb-2">
          <h3 class="text-[13px] font-semibold text-[#374151] dark:text-gray-200 mb-1.5">{{ sub.heading }}</h3>
          <ul class="space-y-1.5">
            {% for it in sub["items"] %}
            <li class="text-[13px] text-gray-700 dark:text-gray-300">
              <div class="flex items-center gap-2">
                <span class="font-semibold">{{ it.lead }}</span>
                {% if it.t is defined and video_id %}<button type="button" onclick="ytSeek({{ it.t }})" class="text-[11px] font-mono text-[#1F6F4A] dark:text-[#34A66A] hover:underline">⏱{{ "%d:%02d:%02d"|format(it.t // 3600, it.t % 3600 // 60, it.t % 60) if it.t >= 3600 else "%d:%02d"|format(it.t // 60, it.t % 60) }}</button>{% endif %}
              </div>
              {% if it.bullets %}
              <ul class="ml-4 mt-1 space-y-1">
                {% for b in it.bullets %}
                <li class="flex gap-2"><span class="text-[#1F6F4A] dark:text-[#34A66A] flex-shrink-0">·</span><span class="leading-relaxed">{{ b }}</span></li>
                {% endfor %}
              </ul>
              {% endif %}
            </li>
            {% endfor %}
          </ul>
        </div>
        {% endfor %}
      </div>
      {% endfor %}
    </div>
    {% else %}
    <!-- 핵심 포인트 (quick) -->
    {% set kp_list = note.key_points if note.key_points is not string else (note.key_points | fromjson) %}
    {% if kp_list %}
    <div class="mb-4">
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">핵심 포인트</h3>
      <ul class="space-y-1.5">
        {% for point in kp_list %}
        <li class="flex gap-2 text-[13px] text-gray-700 dark:text-gray-300">
          <span class="text-[#1F6F4A] dark:text-[#34A66A] flex-shrink-0 font-bold">·</span>
          <span class="leading-relaxed">{{ point }}</span>
        </li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
    {% endif %}
```

- [ ] **Step 2: Remove 핵심 논거 block**

`<!-- 핵심 논거 (상세 정리만) -->` 주석부터 그 `{% if note.main_arguments %} ... {% endif %}{% endif %}` 블록 전체를 **삭제**한다. (인사이트/탐구할 질문 블록은 그대로 둔다.)

- [ ] **Step 3: Sanity render (no Jinja error)**

Run:
```bash
python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print('detail', c.get('/api/items/1/detail').status_code)"
```
Expected: `detail 200`

- [ ] **Step 4: Commit**

```bash
git add templates/partials/note_detail_modal.html
git commit -m "feat: modal renders hierarchical sections + TOC, drops 핵심 논거"
```

- [ ] **Step 5: Browser verification (manual)**

1. 서버 재시작 후 `http://localhost:8000`.
2. **YouTube URL을 상세 정리(detailed)로 분석** (`https://youtu.be/dQw4w9WgXcQ`): 큐 진행 카드 → 완료 후 목록 갱신.
3. 그 노트 "전체 보기": 한 줄 요약 → 목차(앵커 클릭 시 섹션 스크롤) → `## 1.`/`### 1.1` 계층 본문 + 굵은 lead + `⏱m:ss` 클릭 시 임베드 영상 이동 → 하단 인사이트/탐구할 질문. 핵심 논거 미표시.
4. 회귀: 기존 quick 노트 "전체 보기"는 핵심 포인트(평면) 그대로.

---

## 최종 검증

- [ ] `python -m pytest -q` — 전체 통과, 신규 실패 없음.
- [ ] Task 7 브라우저 검증 통과(목차/계층/⏱ 이동/인사이트·질문/핵심 논거 제거/quick 회귀).
