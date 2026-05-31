# 각주 + 전체 화면 Read View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YouTube 노트의 paragraph/item 본문 끝에 `[1][2][3]` 첨자 형태 각주를 두고, 클릭 시 영상 점프. 모달에 "📖 전체 화면" 버튼으로 새 `/items/{id}/read` view 열림. read view는 좌측 영상+트랜스크립트, 우측 본문+각주.

**Architecture:** paragraph/item 데이터 모델을 `{text, refs: [{t, snippet?}, ...]}`로 확장(기존 `quote/t` 제거, 옛 노트는 템플릿 fallback). LLM prompt에 refs 출력 지시. DB에 `items.transcript_segments` 컬럼 추가해 자막 segments 저장. 새 라우트 `/items/{id}/read` + `templates/read.html`. 모달과 read view 둘 다 신규 `templates/macros.html::ref_chips` 매크로로 첨자 렌더.

**Tech Stack:** FastAPI + HTMX + Jinja2 + Tailwind, SQLite(aiosqlite), Anthropic/OpenAI SDK, pytest. 브랜치: `feature/footnote-citations-2026-05-31`.

---

## File Structure

**Create:**
- `templates/macros.html` — `ref_chips` 단일 매크로.
- `templates/read.html` — 전체 화면 read view.
- `tests/test_routes_read.py` — read view 라우트 테스트 (3개).

**Modify:**
- `models.py` — `transcript_segments` 마이그레이션.
- `services/storage.py` — `_JSON_FIELDS` 확장, `save_note(segments=)` 파라미터, INSERT 1 컬럼 추가.
- `services/ai/claude.py` — `_build_refs` 신규, `_build_paragraphs`/`_build_sections` refs 빌드로 교체, 3 prompts 중 `TIER2_PROMPT`/`DETAILED_PROMPT` refs schema (TIER2_CODE는 그대로).
- `services/ai/openai_provider.py` — `_build_refs` import만 (claude.py가 정의).
- `routers/youtube.py` — `save_note(segments=data["segments"])`.
- `routers/items.py` — `GET /{note_id}/read` 핸들러.
- `templates/partials/note_detail_modal.html` — paragraph 끝 `ref_chips` 호출 + 우상단 📖 버튼.
- `tests/test_storage.py` / `tests/test_models.py` / `tests/test_claude_provider.py` / `tests/test_openai_provider.py` / `tests/test_routes_youtube.py` / `tests/test_routes_items.py` — 신규/갱신 테스트.

기존 126 → 135 예상 (+9).

---

## Task 1: DB 마이그레이션 + storage segments round-trip

**Files:**
- Modify: `models.py`, `services/storage.py`
- Test: `tests/test_models.py`, `tests/test_storage.py`

- [ ] **Step 1: 실패 테스트 2개**

`tests/test_models.py` 맨 아래에 append:
```python
@pytest.mark.asyncio
async def test_init_db_adds_transcript_segments_column_idempotently(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "t.db")
    await init_db(db_path)
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cur.fetchall()]
    assert "transcript_segments" in cols
```

`tests/test_storage.py` 맨 아래에 append:
```python
@pytest.mark.asyncio
async def test_save_note_with_segments(db, tmp_path):
    segments = [{"t": 0, "text": "안녕"}, {"t": 5, "text": "코끼리"}]
    nid = await save_note(
        db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
        source_url="u", result=make_result(), ai_provider="claude",
        segments=segments,
    )
    note = await get_note(db, nid)
    assert note["transcript_segments"] == segments


@pytest.mark.asyncio
async def test_save_note_segments_defaults_empty(db, tmp_path):
    nid = await save_note(
        db_path=db, vault_path=str(tmp_path/"vault"), source_type="text",
        source_url="u", result=make_result(), ai_provider="claude",
    )
    note = await get_note(db, nid)
    assert note["transcript_segments"] == []
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_models.py tests/test_storage.py -k "segments or transcript" -v
```
Expected: FAIL.

- [ ] **Step 3a: `models.py` 마이그레이션** — `init_db` 안 다른 `_ensure_column` 호출 옆에 추가:
```python
    await _ensure_column(db, "transcript_segments", "TEXT")
```

- [ ] **Step 3b: `services/storage.py` — `_JSON_FIELDS` 확장**

기존:
```python
_JSON_FIELDS = ("tags", "key_points", "sections",
                "insights", "questions_raised", "ai_models", "timeline", "paragraphs")
```
신규 (`transcript_segments` 추가):
```python
_JSON_FIELDS = ("tags", "key_points", "sections",
                "insights", "questions_raised", "ai_models", "timeline", "paragraphs",
                "transcript_segments")
```

- [ ] **Step 3c: `services/storage.py::save_note` 시그니처 + INSERT 확장**

시그니처에 `segments: list | None = None` 추가:
```python
async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_id: int | None = None,
    timeline: list | None = None,
    segments: list | None = None,
) -> int:
```

INSERT 컬럼 리스트에 `transcript_segments` 추가(현재 18 → 19):
```python
        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, insights, questions_raised,
                ai_provider, ai_models, api_cost_usd, md_file_path, project_id,
                timeline, paragraphs, transcript_segments)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, result.title, source_url, result.summary,
                json.dumps(result.key_points, ensure_ascii=False),
                json.dumps(result.sections, ensure_ascii=False),
                json.dumps(result.tags, ensure_ascii=False),
                result.suggested_topic, result.summary_mode,
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                ai_provider,
                json.dumps(result.models_used, ensure_ascii=False),
                result.cost_usd, md_path, project_id,
                json.dumps(timeline or [], ensure_ascii=False),
                json.dumps(result.paragraphs or [], ensure_ascii=False),
                json.dumps(segments or [], ensure_ascii=False),
            )
        )
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_models.py tests/test_storage.py -k "segments or transcript" -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 129 passed (126 + 3 new).

```
git add models.py services/storage.py tests/test_models.py tests/test_storage.py
git commit -m "feat: transcript_segments column + save_note segments round-trip

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `_build_refs` 헬퍼

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: 실패 테스트 3개**

`tests/test_claude_provider.py` 맨 아래에 append:
```python
def test_build_refs_keeps_t_and_snippet():
    from services.ai.claude import _build_refs
    data = [
        {"t": "30", "snippet": "  원문  "},
        {"t": 90},
    ]
    assert _build_refs(data) == [
        {"t": 30, "snippet": "원문"},
        {"t": 90},
    ]


def test_build_refs_skips_invalid():
    from services.ai.claude import _build_refs
    data = [
        "notdict",
        {"snippet": "no t"},
        {"t": "1:30", "snippet": "non-numeric t"},
        {"t": 5, "snippet": ""},
    ]
    assert _build_refs(data) == [{"t": 5}]


def test_build_refs_empty_input():
    from services.ai.claude import _build_refs
    assert _build_refs([]) == []
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_claude_provider.py -k build_refs -v
```
Expected: ImportError.

- [ ] **Step 3: `_build_refs` 추가** — `services/ai/claude.py`, `_build_paragraphs` 함수 바로 뒤에 append:
```python
def _build_refs(refs_raw: list) -> list[dict]:
    """LLM 응답 ref list → [{t, snippet?}]. t 누락/비숫자 skip; snippet 비면 키 생략."""
    out = []
    for r in refs_raw:
        if not isinstance(r, dict):
            continue
        t = _to_t(r.get("t"))
        if t is None:
            continue
        ref = {"t": t}
        snippet = str(r.get("snippet", "")).strip()
        if snippet:
            ref["snippet"] = snippet
        out.append(ref)
    return out
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_claude_provider.py -k build_refs -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 132 passed (129 + 3 new).

```
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: _build_refs helper for footnote citation parsing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `_build_paragraphs`/`_build_sections` refs 통합 + 기존 테스트 갱신

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: 기존 테스트 갱신**

`tests/test_claude_provider.py::test_build_paragraphs_keeps_text_quote_and_t` 본문 교체:
```python
def test_build_paragraphs_keeps_text_quote_and_t():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        {"text": "  문단 1  ", "refs": [{"t": "30", "snippet": "원문"}, {"t": 60}]},
        {"text": "문단 2"},  # refs 없음
    ]}
    assert _build_paragraphs(data) == [
        {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}, {"t": 60}]},
        {"text": "문단 2", "refs": []},
    ]
```

`test_build_paragraphs_skips_invalid` 본문 교체:
```python
def test_build_paragraphs_skips_invalid():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        "notdict",
        {"text": ""},
        {"refs": [{"t": 5}]},  # text 없음 → skip
        {"text": "ok"},  # refs 없으면 빈 list
    ]}
    assert _build_paragraphs(data) == [{"text": "ok", "refs": []}]
```

`test_build_sections_hierarchy_and_timestamps` 본문에서 items refs로 교체:
```python
def test_build_sections_hierarchy_and_timestamps():
    from services.ai.claude import _build_sections
    data = {"sections": [
        {"heading": "1. 대주제", "t": "0", "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "  문단 본문  ", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "두 번째"},
                {"text": "", "refs": [{"t": 5}]},  # text 없음 skip
            ]},
        ]},
    ]}
    assert _build_sections(data) == [
        {"heading": "1. 대주제", "t": 0, "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "문단 본문", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "두 번째", "refs": []},
            ]},
        ]},
    ]
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_claude_provider.py -k "build_paragraphs or build_sections" -v
```
Expected: FAIL — 기존 코드가 quote/t 빌드해서 결과 다름.

- [ ] **Step 3: `_build_paragraphs` 본문 교체** — `services/ai/claude.py`

기존 함수 본문(quote/t 가드 분기)을 다음으로 전면 교체:
```python
def _build_paragraphs(data: dict) -> list[dict]:
    """LLM 응답 dict → [{text, refs}]. text 비면 skip; refs는 _build_refs 가드."""
    out = []
    for p in data.get("paragraphs", []):
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        out.append({"text": text, "refs": _build_refs(p.get("refs", []))})
    return out
```

- [ ] **Step 4: `_build_sections` items loop 본문 교체**

`_build_sections` 내부의 `for it in sub.get("items", []):` 루프 본문을 다음으로 교체:
```python
            items = []
            for it in sub.get("items", []):
                if not isinstance(it, dict):
                    continue
                text = str(it.get("text", "")).strip()
                if not text:
                    continue
                items.append({"text": text, "refs": _build_refs(it.get("refs", []))})
```

- [ ] **Step 5: 통과 확인**
```
python -m pytest tests/test_claude_provider.py -k "build_paragraphs or build_sections" -v
```
Expected: 모두 PASS.

- [ ] **Step 6: 전체 회귀 — 기존 prompts/summarize 테스트가 quote/t 의존이면 fail 예상**

```
python -m pytest -q
```

기대: 일부 테스트(`test_summarize_quick_returns_paragraphs`, `test_openai_quick_returns_paragraphs`, 모달 라우트 테스트의 fallback 관련 등)가 FAIL할 수 있음. 그것들은 Task 4(prompts 갱신)에서 함께 수정. **이 task의 commit 시점에는 fail 허용** — Task 4까지 한 흐름으로 묶임.

- [ ] **Step 7: 커밋**
```
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: _build_paragraphs/_build_sections produce refs instead of quote+t

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Prompts 갱신 + summarize 통합 테스트

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py`, `tests/test_openai_provider.py`

- [ ] **Step 1: 기존 통합 테스트 갱신 + 신규 추가**

`tests/test_claude_provider.py::test_summarize_quick_returns_paragraphs` 본문 교체:
```python
@pytest.mark.asyncio
async def test_summarize_quick_returns_paragraphs(provider):
    import json
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [],
        "summary": "한 줄 요약 2~3문장.",
        "paragraphs": [
            {"text": "첫 문단", "refs": [{"t": 12, "snippet": "원문 인용"}, {"t": 25, "snippet": "또 다른"}]},
            {"text": "두 번째 문단", "refs": []},
        ],
        "tags": ["x"], "suggested_topic": "AI/ML",
    }, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.summary == "한 줄 요약 2~3문장."
    assert res.paragraphs == [
        {"text": "첫 문단", "refs": [{"t": 12, "snippet": "원문 인용"}, {"t": 25, "snippet": "또 다른"}]},
        {"text": "두 번째 문단", "refs": []},
    ]
```

`tests/test_claude_provider.py::test_summarize_detailed_builds_sections` 본문 교체 (item에 refs):
```python
@pytest.mark.asyncio
async def test_summarize_detailed_builds_sections(provider):
    import json
    tier2 = MagicMock()
    tier2.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "summary": "한 줄 요약",
        "tags": ["x"], "suggested_topic": "AI",
        "sections": [{"heading": "1. A", "t": 0, "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "문단 2", "refs": []},
            ]}]}],
    }, ensure_ascii=False))]
    tier2.usage = MagicMock(input_tokens=10, output_tokens=10)
    tier3 = MagicMock()
    tier3.content = [MagicMock(text=json.dumps({"insights": ["i"], "questions_raised": ["q"]}))]
    tier3.usage = MagicMock(input_tokens=5, output_tokens=5)
    with patch.object(provider._client.messages, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("[0:00] hi", "youtube", "detailed", [])
    items = res.sections[0]["subsections"][0]["items"]
    assert items[0] == {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]}
    assert items[1] == {"text": "문단 2", "refs": []}
    assert res.insights == ["i"]
```

`tests/test_openai_provider.py::test_openai_quick_returns_paragraphs` 본문 교체:
```python
@pytest.mark.asyncio
async def test_openai_quick_returns_paragraphs(provider):
    import json
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "요약",
        "paragraphs": [{"text": "문단", "refs": [{"t": 30, "snippet": "원문"}]}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, return_value=tier2):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.paragraphs == [{"text": "문단", "refs": [{"t": 30, "snippet": "원문"}]}]
```

`tests/test_openai_provider.py::test_openai_summarize_detailed_builds_sections` 본문에서 items refs로 변경 (동일 패턴):
```python
@pytest.mark.asyncio
async def test_openai_summarize_detailed_builds_sections(provider):
    import json
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "summary": "요약",
        "tags": [], "suggested_topic": "",
        "sections": [{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]},
                {"text": "문단 2", "refs": []},
            ]}]}],
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    tier3 = MagicMock()
    tier3.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "insights": ["i"], "questions_raised": ["q"],
    })))]
    tier3.usage = MagicMock(prompt_tokens=5, completion_tokens=5)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, side_effect=[tier2, tier3]):
        res = await provider.summarize("input", "youtube", "detailed", [])
    items = res.sections[0]["subsections"][0]["items"]
    assert items[0] == {"text": "문단 1", "refs": [{"t": 30, "snippet": "원문"}]}
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -q
```
Expected: 일부 FAIL — prompts가 아직 quote/t를 출력하도록 명시되어 있음. 실제 mock 응답은 새 shape이므로 통합 테스트는 PASS, prompt 텍스트 검증 같은 것은 별도 없으면 OK.

- [ ] **Step 3a: `TIER2_PROMPT` 교체** — `services/ai/claude.py`

기존 `TIER2_PROMPT` 전체 교체:
```python
TIER2_PROMPT = """다음 내용을 분석하여 노트를 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 각 문단(text)을 뒷받침할 원문 1~3개를 refs 리스트에 넣습니다. 각 ref는 {{"t": 시작_시각_초, "snippet": "원문 한 문장(verbatim)"}}.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있을 때만 t를 채웁니다. 타임스탬프가 없으면 refs를 비웁니다(빈 list).

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자, "reading_time_min": 숫자,
  "sections": [],
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "paragraphs": [
    {{"text": "한국어 문단", "refs": [{{"t": 30, "snippet": "원문 한 문장"}}, {{"t": 65, "snippet": "다른 원문"}}]}},
    {{"text": "다른 문단", "refs": []}}
  ],
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""
```

- [ ] **Step 3b: `TIER2_CODE_PROMPT` 갱신** — `services/ai/claude.py`

코드 소스는 시각 없음 → refs 항상 빈 list. 기존 전체 교체:
```python
TIER2_CODE_PROMPT = """다음 GitHub 레포지토리 정보를 분석하여 개발자 노트를 작성하세요.
기존 주제 목록: {existing_topics}

레포지토리 정보:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 코드/문서 소스는 영상 타임스탬프가 없으므로 refs는 항상 빈 리스트로 둡니다.

JSON으로 응답하세요:
{{"title": "owner/repo — 한 줄 설명",
  "language": "ko",
  "word_count": 0, "reading_time_min": 0, "sections": [],
  "summary": "프로젝트 목적과 핵심 기능을 2~3문장으로 설명",
  "paragraphs": [
    {{"text": "한국어 문단", "refs": []}},
    {{"text": "다른 문단", "refs": []}}
  ],
  "tags": ["언어", "프레임워크", "도메인키워드"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""
```

- [ ] **Step 3c: `DETAILED_PROMPT` 교체** — `services/ai/claude.py`

전체 교체:
```python
DETAILED_PROMPT = """다음 내용을 분석하여 상세 노트를 계층 구조로 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 5~12개의 의미 단위 대섹션(heading: "1. ...", "2. ...")으로 나눕니다.
- 각 대섹션은 1개 이상의 소섹션(heading: "1.1 ...")을 가지며, 각 소섹션은 2~4개의 문단형 항목(items)을 가집니다.
- 각 item은 한국어 문단 text와, 그 문단을 뒷받침할 원문 1~3개를 refs 리스트에 넣습니다 (각 ref: {{"t": 시작_시각_초, "snippet": "원문 한 문장(verbatim)"}}).
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있을 때만 t를 채웁니다. 타임스탬프가 없으면 refs는 빈 list, 섹션/소섹션의 t도 생략합니다.

JSON으로만 응답하세요:
{{"title": "제목", "language": "ko|en",
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명",
  "sections": [
    {{"heading": "1. 대주제", "t": 10, "subsections": [
      {{"heading": "1.1 소주제", "items": [
        {{"text": "한국어 문단(2~4문장)", "refs": [{{"t": 12, "snippet": "원문 한 문장"}}, {{"t": 25, "snippet": "다른 원문"}}]}},
        {{"text": "다른 문단", "refs": []}}
      ]}}
    ]}}
  ]}}
(t는 타임스탬프가 있을 때만 넣고, 없으면 키를 생략하세요.)"""
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -q
```
Expected: 모두 PASS.

- [ ] **Step 5: 전체 회귀 — 기존 fallback 테스트 확인**

```
python -m pytest -q
```

기대: 모달의 옛 노트 fallback 테스트(`test_modal_renders_legacy_lead_bullets_items` 등)는 데이터 모델 변경 영향 X — 통과. quick `paragraphs` 노트 fallback (옛 `quote+t`)도 Task 7에서 처리. 만약 다른 테스트가 paragraph의 `quote` 키 의존이라면 그건 즉시 fix(이 task 안에).

Expected: 132 + Task 1-3 누적 = 132 passed (이 task는 새 테스트 0).

- [ ] **Step 6: 커밋**
```
git add services/ai/claude.py tests/test_claude_provider.py tests/test_openai_provider.py
git commit -m "feat: prompts emit refs schema; providers wire new paragraph shape

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `routers/youtube.py` — segments → save_note 전달

**Files:**
- Modify: `routers/youtube.py`
- Test: `tests/test_routes_youtube.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_routes_youtube.py` append

```python
@pytest.mark.asyncio
async def test_youtube_pipes_segments_to_save_note():
    """extract 결과의 segments가 save_note의 segments kwarg로 전달."""
    captured = {}
    async def fake_enqueue(task, fn): captured["fn"] = fn
    fake_ai = AsyncMock(); fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        paragraphs=[], cost_usd=0.0, models_used=["m"])

    segments_payload = [{"t": 0, "text": "안녕"}, {"t": 5, "text": "코끼리"}]
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.youtube_title", new_callable=AsyncMock, return_value="T"), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "x", "video_id": "v", "native_chapters": None,
                             "segments": segments_payload}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")), \
         patch("routers.youtube.capture_chapter_screenshots", new_callable=AsyncMock, side_effect=lambda u,c,v,s: c):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc",
                                               "provider": "claude", "mode": "quick"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    assert mock_save.call_args.kwargs["segments"] == segments_payload
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_routes_youtube.py -k pipes_segments -v
```
Expected: KeyError or AssertionError — save_note가 segments kwarg 안 받음.

- [ ] **Step 3: do_work 수정** — `routers/youtube.py`

`save_note(...)` 호출에 `segments=data["segments"]` 추가:
```python
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
            segments=data["segments"],
        )
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_routes_youtube.py -k pipes_segments -v
```
Expected: PASS.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 133 passed (132 + 1 new).

```
git add routers/youtube.py tests/test_routes_youtube.py
git commit -m "feat: pipe transcript segments to save_note

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: `templates/macros.html` + 모달 첨자 + 📖 버튼 + fallback

**Files:**
- Create: `templates/macros.html`
- Modify: `templates/partials/note_detail_modal.html`
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 3개** — `tests/test_routes_items.py` append

```python
@pytest.mark.asyncio
async def test_modal_paragraph_refs_render_chips():
    """refs 있는 quick paragraph → 모달에 [1][2] 첨자 노출."""
    note = dict(MOCK_NOTE)
    note["source_url"] = "https://youtu.be/dQw4w9WgXcY"
    note["summary_mode"] = "quick"
    note["paragraphs"] = [
        {"text": "본문 한 줄.", "refs": [{"t": 30, "snippet": "원문1"}, {"t": 60, "snippet": "원문2"}]},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "ytSeek(30)" in resp.text
    assert "ytSeek(60)" in resp.text


@pytest.mark.asyncio
async def test_modal_legacy_quote_paragraph_renders_single_chip():
    """옛 노트(refs 없고 quote+t만 있음) → 첨자 1개로 fallback."""
    note = dict(MOCK_NOTE)
    note["source_url"] = "https://youtu.be/dQw4w9WgXcY"
    note["summary_mode"] = "quick"
    note["paragraphs"] = [
        {"text": "옛 본문.", "quote": "옛 원문", "t": 42},
    ]
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert "ytSeek(42)" in resp.text


@pytest.mark.asyncio
async def test_modal_shows_full_screen_link_for_youtube():
    """YouTube 노트 모달 우상단에 /items/{id}/read 링크 노출."""
    note = dict(MOCK_NOTE)
    note["source_url"] = "https://youtu.be/dQw4w9WgXcY"
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert 'href="/items/1/read"' in resp.text
    assert "📖" in resp.text
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_routes_items.py -k "refs_render or legacy_quote or full_screen_link" -v
```
Expected: 모두 FAIL.

- [ ] **Step 3a: `templates/macros.html` 생성**

```jinja
{% macro ref_chips(refs, video_id) %}
{%- if refs and video_id -%}
<span class="inline-flex gap-1 ml-1 align-super">
  {%- for r in refs %}
  <button type="button"
          onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ r.t }})"
          title="{{ r.snippet }}"
          class="text-[10px] px-1 bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] hover:bg-[#1F6F4A] hover:text-white rounded transition-colors">{{ loop.index }}</button>
  {%- endfor %}
</span>
{%- endif -%}
{% endmacro %}


{% macro effective_refs(p) %}
{#- 옛 노트 fallback: refs 비고 quote+t 있으면 단일 ref로 변환 -#}
{%- if p.refs -%}
{{ p.refs }}
{%- elif p.quote and p.t is defined -%}
{{ [{"t": p.t, "snippet": p.quote}] }}
{%- else -%}
{{ [] }}
{%- endif -%}
{% endmacro %}
```

(주: `effective_refs`는 Jinja에서 list 직접 반환 시 문자열로 렌더되는 문제 있음 — 대신 inline `{% set %}`로 처리. macros.html에는 `ref_chips`만 두고 옛 노트 변환은 호출 측 `{% set %}`로 처리.)

수정된 `templates/macros.html`:
```jinja
{% macro ref_chips(refs, video_id) %}
{%- if refs and video_id -%}
<span class="inline-flex gap-1 ml-1 align-super">
  {%- for r in refs %}
  <button type="button"
          onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ r.t }})"
          title="{{ r.snippet }}"
          class="text-[10px] px-1 bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] hover:bg-[#1F6F4A] hover:text-white rounded transition-colors">{{ loop.index }}</button>
  {%- endfor %}
</span>
{%- endif -%}
{% endmacro %}
```

- [ ] **Step 3b: 모달 import + paragraph 첨자 + 📖 버튼**

`templates/partials/note_detail_modal.html` 최상단(`{% macro fmt_ts ... %}` 위)에 import 한 줄 추가:
```jinja
{% from "macros.html" import ref_chips %}
```

paragraph 렌더 부분(quick) 변경 — `{% if p.quote %}`로 quote/t 표기하던 부분을 fallback list 계산 + `ref_chips` 호출로 교체. 현재 모달에서 quick paragraphs 렌더 위치는 lines 165-185 근처(`<!-- 본문 (quick paragraphs) -->`).

찾기 (현재 코드 예상 구조):
```jinja
{% for p in p_list %}
<div>
  <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">{{ p.text }}</p>
  {% if p.quote %}
  <blockquote class="...">
    ... ⏱ 버튼 ...
    &ldquo;{{ p.quote }}&rdquo;
  </blockquote>
  {% endif %}
</div>
{% endfor %}
```

신규로 교체:
```jinja
{% for p in p_list %}
<div>
  {% set effective = p.refs if p.refs else ([{"t": p.t, "snippet": p.quote}] if (p.get('quote') and p.t is defined) else []) %}
  <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
    {{ p.text }}{{ ref_chips(effective, video_id) }}
  </p>
</div>
{% endfor %}
```

(blockquote 제거 — 첨자만 사용. snippet은 hover title로 표시.)

detailed item 렌더 부분도 동일하게 변경 — `templates/partials/note_detail_modal.html`의 detailed items 블록(현재 lines 122-148, `{% if it.text is defined %}` 분기). 신규:
```jinja
{% for it in sub["items"] %}
{% if it.text is defined %}
{# 신규: 문단 + 각주 #}
<div>
  {% set effective = it.refs if it.refs else ([{"t": it.t, "snippet": it.quote}] if (it.get('quote') and it.t is defined) else []) %}
  <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
    {% if it.text %}{{ it.text }}{% endif %}{{ ref_chips(effective, video_id) }}
  </p>
</div>
{% else %}
{# 백워드 호환: 옛 {lead, bullets} - 변경 없음 #}
... (기존 lead/bullets 블록 그대로) ...
{% endif %}
{% endfor %}
```

기존 detailed 블록의 `<blockquote>` 부분(refs 도입으로 더 이상 안 보임) 제거.

📖 전체 화면 버튼 추가 — 우상단 휴지통(`right-14`) 옆에. 휴지통과 ✕ 사이에 새 버튼.

현재 모달 헤더 (lines 11-25 근처):
```html
    <!-- 삭제 -->
    <button hx-delete="..." aria-label="삭제" ... class="absolute top-4 right-14 ...">🗑</button>
    <!-- 닫기 -->
    <button onclick="closeNoteModal()" ... class="absolute top-4 right-4 ...">✕</button>
```

신규(휴지통 → right-24, 📖 → right-14, ✕ → right-4 유지):
```html
    <!-- 삭제 -->
    <button hx-delete="/api/items/{{ note.id }}"
            hx-confirm="이 노트를 삭제하시겠어요? .md 파일도 함께 사라집니다."
            hx-target="#note-card-{{ note.id }}"
            hx-swap="outerHTML"
            hx-on::after-request="if(event.detail.successful) closeNoteModal()"
            title="삭제" aria-label="삭제"
            class="absolute top-4 right-24 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/40 transition-colors text-sm">🗑</button>
    {% if video_id %}
    <!-- 전체 화면 -->
    <a href="/items/{{ note.id }}/read" target="_blank"
       title="전체 화면" aria-label="전체 화면 보기"
       class="absolute top-4 right-14 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 transition-colors text-sm">📖</a>
    {% endif %}
    <!-- 닫기 -->
    <button onclick="closeNoteModal()"
            class="absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 transition-colors text-sm font-bold">✕</button>
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_routes_items.py -k "refs_render or legacy_quote or full_screen_link" -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 136 passed (133 + 3 new).

```
git add templates/macros.html templates/partials/note_detail_modal.html tests/test_routes_items.py
git commit -m "feat: modal renders [N] ref chips + full-screen button

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: `GET /items/{id}/read` 라우트

**Files:**
- Modify: `routers/items.py`
- Test: `tests/test_routes_read.py` (new)

- [ ] **Step 1: 새 테스트 파일 생성** — `tests/test_routes_read.py`

```python
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app


YT_NOTE = {
    "id": 1, "type": "youtube", "title": "T", "summary": "요약",
    "tags": [], "topic": "", "summary_mode": "quick",
    "key_points": [], "paragraphs": [{"text": "본문", "refs": [{"t": 30, "snippet": "원문"}]}],
    "sections": [], "ai_provider": "claude", "api_cost_usd": 0.01,
    "created_at": "2026-05-31",
    "source_url": "https://youtu.be/dQw4w9WgXcY",
    "transcript_segments": [{"t": 0, "text": "안녕"}, {"t": 5, "text": "코끼리"}],
    "timeline": [{"t": 0, "label": "인트로"}],
    "insights": [], "questions_raised": [],
}


@pytest.mark.asyncio
async def test_read_view_renders_youtube_note():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=YT_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code == 200
    # 영상 임베드
    assert 'id="yt-player"' in resp.text
    # 트랜스크립트 segment 들
    assert "안녕" in resp.text and "코끼리" in resp.text
    # 본문 paragraph
    assert "본문" in resp.text
    # ref 첨자(클릭 시 ytSeek)
    assert "ytSeek(30)" in resp.text


@pytest.mark.asyncio
async def test_read_view_redirects_non_youtube():
    pdf_note = {**YT_NOTE, "type": "pdf", "source_url": "paper.pdf"}
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=pdf_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/1/read")
    assert resp.status_code in (302, 307)
    assert resp.headers.get("location") == "/"


@pytest.mark.asyncio
async def test_read_view_404_when_note_missing():
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as c:
            resp = await c.get("/api/items/999/read")
    assert resp.status_code in (302, 307, 404)  # redirect or 404 OK
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_routes_read.py -v
```
Expected: 404 (route not defined).

- [ ] **Step 3a: import 확장** — `routers/items.py` 상단

기존 fastapi import에 `RedirectResponse` 추가:
```python
from fastapi.responses import JSONResponse, HTMLResponse
```
→
```python
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
```

- [ ] **Step 3b: read view 핸들러 추가** — `routers/items.py`, `get_item_detail` 함수 직후에 append:
```python
@router.get("/{note_id}/read")
async def read_view(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note or note.get("type") != "youtube":
        return RedirectResponse("/", status_code=302)
    video_id = youtube_video_id(note.get("source_url"))
    return templates.TemplateResponse(
        request, "read.html", {"note": note, "video_id": video_id},
    )
```

- [ ] **Step 4: `templates/read.html` 임시 stub 생성** (Task 8에서 완성)

Task 8까지 라우트는 동작해야 하므로 최소 stub:
```jinja
{% extends "base.html" %}
{% from "macros.html" import ref_chips %}
{% block body %}
{# read view stub — Task 8에서 완성 #}
<div class="p-4">
  <h1 class="text-lg font-bold">{{ note.title }}</h1>
  <div id="yt-player" data-video-id="{{ video_id }}"></div>
  <ul>
    {% set seg_list = note.transcript_segments if note.transcript_segments is not string else (note.transcript_segments | fromjson) %}
    {% for s in seg_list %}
    <li>{{ s.text }}</li>
    {% endfor %}
  </ul>
  {% set p_list = note.paragraphs if note.paragraphs is not string else (note.paragraphs | fromjson) %}
  {% for p in p_list %}
  <p>{{ p.text }}{{ ref_chips(p.refs, video_id) }}</p>
  {% endfor %}
</div>
{% endblock %}
```

(`base.html`에 `{% block body %}{% endblock %}` 같은 게 있는지 확인 필요. 없다면 base.html에 block 추가 또는 read.html을 base 확장 없이 standalone으로 작성. base.html은 navbar/sidebar/layout이 거의 다 고정이라 block 없음 — 따라서 read.html은 별도 standalone html로 작성. 아래는 standalone 버전:)

```jinja
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{{ note.title }} — liby</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwind.config = { darkMode: 'class' }</script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="https://www.youtube.com/iframe_api"></script>
</head>
<body class="bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100">
{% from "macros.html" import ref_chips %}
<div class="p-4">
  <h1 class="text-lg font-bold">{{ note.title }}</h1>
  <div id="yt-player" data-video-id="{{ video_id }}" class="aspect-video"></div>
  <ul class="my-4">
    {% set seg_list = note.transcript_segments if note.transcript_segments is not string else (note.transcript_segments | fromjson) %}
    {% for s in seg_list %}
    <li onclick="ytSeek({{ s.t }})" class="cursor-pointer hover:bg-gray-100 px-2 py-1 text-sm">[{{ "%d:%02d"|format(s.t // 60, s.t % 60) }}] {{ s.text }}</li>
    {% endfor %}
  </ul>
  {% set p_list = note.paragraphs if note.paragraphs is not string else (note.paragraphs | fromjson) %}
  {% for p in p_list %}
  <p class="my-2">{{ p.text }}{{ ref_chips(p.refs, video_id) }}</p>
  {% endfor %}
</div>
<script>
let ytPlayer = null;
function initYtPlayer() {
  const el = document.getElementById('yt-player');
  if (!el) return;
  const id = el.dataset.videoId;
  if (!id) return;
  ytPlayer = new YT.Player('yt-player', { videoId: id });
}
function ytSeek(sec) {
  if (ytPlayer && ytPlayer.seekTo) { ytPlayer.seekTo(sec, true); ytPlayer.playVideo(); }
}
window.onYouTubeIframeAPIReady = function () { initYtPlayer(); };
</script>
</body>
</html>
```

- [ ] **Step 5: 통과 확인**
```
python -m pytest tests/test_routes_read.py -v
```
Expected: 3 passed.

- [ ] **Step 6: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 139 passed (136 + 3 new).

```
git add routers/items.py templates/read.html tests/test_routes_read.py
git commit -m "feat: GET /items/{id}/read endpoint with stub view

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: `templates/read.html` 정식 구현 (좌우 분할)

**Files:**
- Modify: `templates/read.html`

라우트 테스트(Task 7)는 통과 상태 유지 — 같은 element id/attribute 보존하면 됨. 이 task는 시각적 완성도 위주.

- [ ] **Step 1: read.html 전체 교체**

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{{ note.title }} — liby</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwind.config = { darkMode: 'class' }</script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="https://www.youtube.com/iframe_api"></script>
</head>
<body class="bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100">
{% from "macros.html" import ref_chips %}

<!-- 헤더 -->
<header class="border-b border-[#E2E8E4] dark:border-gray-700 px-5 py-3 flex items-center gap-3">
  <a href="/" class="text-[#1F6F4A] dark:text-[#34A66A] font-bold">📚 liby</a>
  <span class="text-gray-400 text-sm">/</span>
  <h1 class="text-sm font-semibold text-gray-700 dark:text-gray-200 truncate flex-1">{{ note.title }}</h1>
  <a href="{{ note.source_url }}" target="_blank" class="text-xs text-gray-400 hover:text-[#1F6F4A]">원본 영상 ↗</a>
</header>

<!-- 본문 좌우 분할 -->
<div class="md:grid md:grid-cols-5 md:gap-4 p-4 max-w-screen-xl mx-auto">
  <!-- 좌측: 영상 + 트랜스크립트 (sticky) -->
  <aside class="md:col-span-2 md:sticky md:top-4 md:self-start md:max-h-[calc(100vh-5rem)] md:overflow-y-auto">
    <div class="aspect-video bg-black rounded-lg overflow-hidden mb-3">
      <div id="yt-player" data-video-id="{{ video_id }}" class="w-full h-full"></div>
    </div>
    {% set seg_list = note.transcript_segments if note.transcript_segments is not string else (note.transcript_segments | fromjson) %}
    {% if seg_list %}
    <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2 mt-4">트랜스크립트</h3>
    <ul class="space-y-0.5 text-[12px]">
      {% for s in seg_list %}
      <li>
        <button type="button" onclick="ytSeek({{ s.t }})"
                class="w-full text-left flex gap-2 text-gray-700 dark:text-gray-300 hover:bg-[#EAF4EE] dark:hover:bg-[#14291E] rounded px-2 py-1 transition-colors">
          <span class="text-[#1F6F4A] dark:text-[#34A66A] font-mono flex-shrink-0">{{ "%d:%02d"|format(s.t // 60, s.t % 60) }}</span>
          <span>{{ s.text }}</span>
        </button>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-[11px] text-gray-400 mt-4">트랜스크립트 없음</p>
    {% endif %}
  </aside>

  <!-- 우측: 본문 + 각주 -->
  <article class="md:col-span-3 prose prose-sm max-w-none dark:prose-invert">
    <!-- 요약 -->
    <section class="mb-6">
      <h2 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">요약</h2>
      <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">{{ note.summary }}</p>
    </section>

    {% set sec_list = note.sections if note.sections is not string else (note.sections | fromjson) %}
    {% if sec_list %}
    <!-- detailed: sections.subsections.items -->
    {% for sec in sec_list %}
    <section class="mb-6">
      <h2 class="text-[14px] font-bold text-gray-800 dark:text-gray-100 mb-3">{{ sec.heading }}</h2>
      {% for sub in sec.get("subsections", []) %}
      <h3 class="text-[12px] font-semibold text-gray-700 dark:text-gray-200 mb-2 mt-3">{{ sub.heading }}</h3>
      <div class="space-y-2">
        {% for it in sub.get("items", []) %}
        {% if it.text is defined %}
        {% set effective = it.refs if it.refs else ([{"t": it.t, "snippet": it.quote}] if (it.get('quote') and it.t is defined) else []) %}
        <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
          {% if it.text %}{{ it.text }}{% endif %}{{ ref_chips(effective, video_id) }}
        </p>
        {% else %}
        {# 레거시 lead/bullets — 그대로 표시(refs 없음) #}
        <div class="text-[13px] text-gray-700 dark:text-gray-300">
          <span class="font-semibold">{{ it.lead }}</span>
          {% if it.bullets %}
          <ul class="ml-4 mt-1">{% for b in it.bullets %}<li>· {{ b }}</li>{% endfor %}</ul>
          {% endif %}
        </div>
        {% endif %}
        {% endfor %}
      </div>
      {% endfor %}
    </section>
    {% endfor %}
    {% else %}
    <!-- quick: paragraphs -->
    {% set p_list = note.paragraphs if note.paragraphs is not string else (note.paragraphs | fromjson) %}
    {% if p_list %}
    <section class="mb-6">
      <h2 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">본문</h2>
      <div class="space-y-3">
        {% for p in p_list %}
        {% set effective = p.refs if p.refs else ([{"t": p.t, "snippet": p.quote}] if (p.get('quote') and p.t is defined) else []) %}
        <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
          {{ p.text }}{{ ref_chips(effective, video_id) }}
        </p>
        {% endfor %}
      </div>
    </section>
    {% endif %}
    {% endif %}

    {% if note.insights %}
    <section class="mb-6">
      <h2 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">인사이트</h2>
      <ul class="text-[13px] text-gray-700 dark:text-gray-300 space-y-1">{% for i in note.insights %}<li>· {{ i }}</li>{% endfor %}</ul>
    </section>
    {% endif %}

    {% if note.questions_raised %}
    <section class="mb-6">
      <h2 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">탐구할 질문</h2>
      <ul class="text-[13px] text-gray-700 dark:text-gray-300 space-y-1">{% for q in note.questions_raised %}<li>· {{ q }}</li>{% endfor %}</ul>
    </section>
    {% endif %}
  </article>
</div>

<script>
let ytPlayer = null;
function initYtPlayer() {
  const el = document.getElementById('yt-player');
  if (!el) return;
  const id = el.dataset.videoId;
  if (!id) return;
  ytPlayer = new YT.Player('yt-player', { videoId: id });
}
function ytSeek(sec) {
  if (ytPlayer && ytPlayer.seekTo) { ytPlayer.seekTo(sec, true); ytPlayer.playVideo(); }
}
window.onYouTubeIframeAPIReady = function () { initYtPlayer(); };
</script>
</body>
</html>
```

- [ ] **Step 2: 라우트 테스트 회귀 확인**
```
python -m pytest tests/test_routes_read.py -v
```
Expected: 3 passed (Task 7과 동일).

- [ ] **Step 3: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 139 passed (unchanged).

```
git add templates/read.html
git commit -m "feat: read.html with split layout (video+transcript / body+refs)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: 브라우저 E2E 검증 (수동)

**Files:** 없음 (모든 작업 통합 검증)

- [ ] **Step 1: 서버 재시작**

```bash
# 기존 uvicorn PID 확인 → Stop-Process
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
**중요**: ffmpeg PATH 포함 — `export PATH="$PATH:/c/Users/<username>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin"`

- [ ] **Step 2: 자막 있는 YouTube 영상 분석**

브라우저 `http://localhost:8000` → YouTube 탭 → 영상 분석.

- [ ] **Step 3: 모달 검증**

- 카드 클릭 → 모달 열림.
- paragraph 끝에 `[1][2][3]` 작은 첨자(영상 시각 백링크) 노출.
- 첨자 클릭 → 모달 안 영상이 해당 시각으로 점프.
- 우상단에 `🗑 📖 ✕` 3 버튼 보임. 📖 클릭 → 새 탭 `/items/{id}/read` 열림.

- [ ] **Step 4: read view 검증**

- 좌측: 영상 임베드 + 트랜스크립트 list (segments 모두).
- 우측: 요약 + 본문 paragraphs/items + 각 paragraph 끝 `[N]` 첨자.
- 트랜스크립트 segment 클릭 → 영상이 해당 시각으로 점프.
- `[N]` 첨자 클릭 → 영상이 해당 시각으로 점프.

- [ ] **Step 5: 옛 노트 백워드 호환 검증**

- 기존 노트(refs 없이 quote+t만 있음) 모달 → `[1]` 첨자 1개로 노출.
- 옛 노트 클릭한 모달의 📖 → read view에서도 fallback `[1]` 표시.

- [ ] **Step 6: 비-YouTube 노트 검증**

- PDF/Text/Code 노트 모달에는 📖 버튼 없음(`{% if video_id %}` 가드).
- 직접 URL로 `/api/items/<pdf-id>/read` 접근 → `/`로 redirect.

검증 완료 시 Plan 종료.
