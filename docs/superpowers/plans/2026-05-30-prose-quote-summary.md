# Prose-Quote Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 빠른·상세 요약의 본문을 불릿/lead 구조에서 "한국어 문단(text) + 원문 인용(quote, 선택) + 시작 시각(t, 선택)" 의 통일된 `block` 단위로 바꿔, 사용자가 AI의 해석과 출처를 함께 확인하게 한다.

**Architecture:** 양 모드 공통 데이터 단위 `{text, quote?, t?}`. 빠른 모드는 `SummaryResult.paragraphs: list[block]`(신규)로, 상세 모드는 기존 계층(`sections[].subsections[].items`)의 item을 `{lead,bullets}` → `block`으로 교체. 프롬프트(`TIER2_PROMPT`/`TIER2_CODE_PROMPT`/`DETAILED_PROMPT`)·파싱 헬퍼·저장/마이그레이션·렌더(md+모달)을 줄줄이 갱신하되, 기존 노트는 모달/마크다운 폴백으로 깨지지 않게 유지.

**Tech Stack:** FastAPI + HTMX + Jinja2 + Tailwind, SQLite(aiosqlite), Anthropic/OpenAI SDK, pytest. 브랜치 `feature/prose-quote-summary`.

---

## `block` 데이터 형태 (모든 태스크 공통 참조)

```jsonc
{
  "text":  "AI가 작성한 한국어 문단(2~4문장)",
  "quote": "원문에서 verbatim 발췌(1~2문장)",   // 선택
  "t":     150                                  // 선택, 인용 시작 시각(초). 영상 자막 [m:ss] 있을 때만
}
```

DB `items.paragraphs`(JSON TEXT, 신설) + 기존 `items.sections`(JSON TEXT) 안의 `subsections[].items`가 모두 이 형태. 백워드 호환: 기존 노트의 `key_points`(quick), `{lead,bullets}`(detailed)는 그대로 두고 렌더에서 신규 필드 우선 → 없으면 옛 필드로 폴백.

---

## Task 1: 스키마 기초(SummaryResult / migration / storage round-trip)

**Files:**
- Modify: `services/ai/base.py`
- Modify: `models.py`
- Modify: `services/storage.py`
- Test: `tests/test_models.py`, `tests/test_storage.py`

- [ ] **Step 1: Add failing test for paragraphs round-trip** — append to `tests/test_storage.py`:

```python
@pytest.mark.asyncio
async def test_save_note_with_paragraphs(db, tmp_path):
    paragraphs = [
        {"text": "AI 해석 문단", "quote": "원문 한 문장", "t": 30},
        {"text": "두 번째 문단"},
    ]
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude",
                          paragraphs=paragraphs)
    note = await get_note(db, nid)
    assert note["paragraphs"] == paragraphs


@pytest.mark.asyncio
async def test_save_note_paragraphs_defaults_empty(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="text",
                          source_url="u", result=make_result(), ai_provider="claude")
    note = await get_note(db, nid)
    assert note["paragraphs"] == []


@pytest.mark.asyncio
async def test_upgrade_to_detailed_persists_paragraphs(db, tmp_path):
    from services.storage import upgrade_to_detailed
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    detailed = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="s", key_points=[], tags=[], suggested_topic="",
        summary_mode="detailed", insights=["i"], questions_raised=["q"],
        paragraphs=[{"text": "문단", "quote": "인용"}], cost_usd=0.0)
    await upgrade_to_detailed(db, nid, detailed)
    note = await get_note(db, nid)
    assert note["paragraphs"] == [{"text": "문단", "quote": "인용"}]
```

- [ ] **Step 2: Verify FAIL**

Run: `python -m pytest tests/test_storage.py -k paragraphs -v`
Expected: FAIL with `TypeError: save_note() got an unexpected keyword argument 'paragraphs'` (or `KeyError: 'paragraphs'` on the dict).

- [ ] **Step 3a: Add `paragraphs` field to `SummaryResult`** — `services/ai/base.py`

In the `@dataclass` SummaryResult, add this line right after `related_concepts: Optional[list[str]] = None` (preserving existing fields):
```python
    paragraphs: list[dict] = field(default_factory=list)  # 신규: 빠른/상세 모두 본문 단위 [{text, quote?, t?}]
```

- [ ] **Step 3b: Add `paragraphs` column migration** — `models.py`

Find the `init_db` body where `_ensure_column(db, "timeline", "TEXT")` is called. Add a sibling call right after it:
```python
        await _ensure_column(db, "paragraphs", "TEXT")
```

- [ ] **Step 3c: Storage — JSON_FIELDS + save_note + upgrade_to_detailed** — `services/storage.py`

(a) `_JSON_FIELDS` tuple: add `"paragraphs"` (kept after `"timeline"`):
```python
_JSON_FIELDS = ("tags", "key_points", "sections", "main_arguments",
                "insights", "questions_raised", "related_concepts", "ai_models", "timeline", "paragraphs")
```

(b) `save_note` signature — add `paragraphs` param after `timeline`:
```python
async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_id: int | None = None,
    timeline: list | None = None,
    paragraphs: list | None = None,
) -> int:
```

(c) Extend the INSERT — append `paragraphs` to the column list, add one more `?`, and append `json.dumps(paragraphs or [], ensure_ascii=False)` as the LAST value:
```python
        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, main_arguments, insights, questions_raised,
                related_concepts, ai_provider, ai_models, api_cost_usd, md_file_path, project_id,
                timeline, paragraphs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                json.dumps(paragraphs or [], ensure_ascii=False),
            )
        )
```
**Column count must equal `?` count must equal value count = 20.** Double-check.

(d) `upgrade_to_detailed`: add `paragraphs=?` to the UPDATE SET list (right after `sections=?`) and the corresponding `json.dumps(result.paragraphs or [], ensure_ascii=False)` to the values tuple (right after the sections value):
```python
        await db.execute(
            """UPDATE items SET
               summary_mode='detailed',
               sections=?,
               paragraphs=?,
               main_arguments=?, insights=?, questions_raised=?,
               related_concepts=?, api_cost_usd=api_cost_usd+?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                json.dumps(result.sections or [], ensure_ascii=False),
                json.dumps(result.paragraphs or [], ensure_ascii=False),
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                result.cost_usd, note_id,
            )
        )
```

- [ ] **Step 4: Add migration idempotency test** — append to `tests/test_models.py`:

```python
@pytest.mark.asyncio
async def test_init_db_adds_paragraphs_column_idempotently(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "t.db")
    await init_db(db_path)
    await init_db(db_path)  # second call must not raise
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cur.fetchall()]
    assert "paragraphs" in cols
```

- [ ] **Step 5: Run, confirm PASS**

```bash
python -m pytest tests/test_storage.py tests/test_models.py -v
```
Expected: all PASS (incl. the 3 new storage tests + 1 new models test). Existing storage tests still pass (`paragraphs` is an additive optional param).

- [ ] **Step 6: Commit**

```bash
git add services/ai/base.py models.py services/storage.py tests/test_storage.py tests/test_models.py
git commit -m "feat: add paragraphs field + migration + storage round-trip"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 2: `_build_paragraphs` 헬퍼 (claude.py)

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: Add failing tests** — append to `tests/test_claude_provider.py`:

```python
def test_build_paragraphs_keeps_text_quote_and_t():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        {"text": "  문단 1  ", "quote": "  인용  ", "t": "30"},
        {"text": "문단 2"},  # quote/t 없음
    ]}
    assert _build_paragraphs(data) == [
        {"text": "문단 1", "quote": "인용", "t": 30},
        {"text": "문단 2"},
    ]


def test_build_paragraphs_skips_invalid():
    from services.ai.claude import _build_paragraphs
    data = {"paragraphs": [
        "notdict",
        {"text": ""},          # 빈 text → skip
        {"quote": "only"},     # text 없음 → skip
        {"text": "ok", "t": "1:30"},  # t 가드: 비숫자 → 키 생략
    ]}
    assert _build_paragraphs(data) == [{"text": "ok"}]
```

- [ ] **Step 2: Verify FAIL**

Run: `python -m pytest tests/test_claude_provider.py -k build_paragraphs -v`
Expected: FAIL with `ImportError: cannot import name '_build_paragraphs'`.

- [ ] **Step 3: Implement** — `services/ai/claude.py`, directly AFTER the existing `_build_sections` function:

```python
def _build_paragraphs(data: dict) -> list[dict]:
    """LLM 응답 dict → [{text, quote?, t?}]. text 비면 skip; t는 _to_t 가드."""
    out = []
    for p in data.get("paragraphs", []):
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        block = {"text": text}
        quote = str(p.get("quote", "")).strip()
        if quote:
            block["quote"] = quote
        t = _to_t(p.get("t"))
        if t is not None:
            block["t"] = t
        out.append(block)
    return out
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_claude_provider.py -k build_paragraphs -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: _build_paragraphs guard helper for prose-quote blocks"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 3: `_build_sections` 의 item 형태 교체 (`{lead,bullets}` → `block`)

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py` (기존 `test_build_sections_hierarchy_and_timestamps` 갱신)

- [ ] **Step 1: Update the existing test** — `tests/test_claude_provider.py`

Replace the body of `test_build_sections_hierarchy_and_timestamps` so the input/expected use the new item shape:
```python
def test_build_sections_hierarchy_and_timestamps():
    from services.ai.claude import _build_sections
    data = {"sections": [
        {"heading": "1. 대주제", "t": "0", "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "  문단 본문  ", "quote": "  원문 인용  ", "t": 30},
                {"text": "두 번째 문단"},     # quote/t 없음
                {"text": "", "quote": "x"},   # text 비면 skip
            ]},
        ]},
    ]}
    assert _build_sections(data) == [
        {"heading": "1. 대주제", "t": 0, "subsections": [
            {"heading": "1.1 소주제", "t": 90, "items": [
                {"text": "문단 본문", "quote": "원문 인용", "t": 30},
                {"text": "두 번째 문단"},
            ]},
        ]},
    ]
```
(`test_build_sections_skips_invalid` already uses only headings/subsections — no change needed.)

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_claude_provider.py::test_build_sections_hierarchy_and_timestamps -v`
Expected: FAIL — the current builder reads `lead`/`bullets` so the new `text` items get dropped.

- [ ] **Step 3: Update the item builder inside `_build_sections`** — `services/ai/claude.py`

Replace the item-loop body (the inner `for it in sub.get("items", []):` block) with:
```python
            items = []
            for it in sub.get("items", []):
                if not isinstance(it, dict):
                    continue
                text = str(it.get("text", "")).strip()
                if not text:
                    continue
                item = {"text": text}
                quote = str(it.get("quote", "")).strip()
                if quote:
                    item["quote"] = quote
                t = _to_t(it.get("t"))
                if t is not None:
                    item["t"] = t
                items.append(item)
```
(The outer structure — section + subsection guards and `t` attachment — stays exactly as it is.)

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_claude_provider.py -k build_sections -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: _build_sections items now {text, quote?, t?} prose blocks"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 4: 프롬프트 갱신 + summarize 와이어링 (양 프로바이더)

**Files:**
- Modify: `services/ai/claude.py` (`TIER2_PROMPT`, `TIER2_CODE_PROMPT`, `DETAILED_PROMPT`, `summarize`)
- Modify: `services/ai/openai_provider.py` (import + `summarize`)
- Test: `tests/test_claude_provider.py`, `tests/test_openai_provider.py`

- [ ] **Step 1: Update existing tests + add new** — `tests/test_claude_provider.py`

Replace `test_summarize_quick_returns_summary_result` (or whichever quick test asserts key_points) with:
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
            {"text": "첫 문단", "quote": "원문 인용", "t": 12},
            {"text": "두 번째 문단"},
        ],
        "tags": ["x"], "suggested_topic": "AI/ML",
    }, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.summary == "한 줄 요약 2~3문장."
    assert res.paragraphs == [
        {"text": "첫 문단", "quote": "원문 인용", "t": 12},
        {"text": "두 번째 문단"},
    ]
    assert res.summary_mode == "quick"
```

And replace the existing `test_summarize_detailed_builds_sections` body so the mock items use new shape and assertions check it:
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
                {"text": "문단 1", "quote": "원문", "t": 30},
                {"text": "문단 2"},
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
    assert items[0] == {"text": "문단 1", "quote": "원문", "t": 30}
    assert items[1] == {"text": "문단 2"}
    assert res.insights == ["i"]
```

Append a mirror test for openai in `tests/test_openai_provider.py`:
```python
@pytest.mark.asyncio
async def test_openai_quick_returns_paragraphs(provider):
    tier2 = MagicMock()
    tier2.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "요약",
        "paragraphs": [{"text": "문단", "quote": "인용"}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False)))]
    tier2.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock, return_value=tier2):
        res = await provider.summarize("text", "youtube", "quick", [])
    assert res.paragraphs == [{"text": "문단", "quote": "인용"}]
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -q`
Expected: FAILs — current prompts emit `key_points`, summarize doesn't populate `paragraphs`, and detailed item shape mismatch.

- [ ] **Step 3a: Replace `TIER2_PROMPT`** — `services/ai/claude.py`

```python
TIER2_PROMPT = """다음 내용을 분석하여 노트를 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 각 문단(text)을 뒷받침할 원문 한 문장이 있으면 verbatim으로 quote에 발췌해 넣고, 없으면 quote 키를 생략합니다.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있으면 quote 시작 시각의 t를 "초 단위 정수"로 넣고, 없으면 생략합니다.

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자, "reading_time_min": 숫자,
  "sections": [],
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "paragraphs": [
    {{"text": "한국어 문단", "quote": "원문에서 발췌한 한 문장", "t": 30}},
    {{"text": "다른 문단"}}
  ],
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""
```

- [ ] **Step 3b: Replace `TIER2_CODE_PROMPT`** — `services/ai/claude.py`

```python
TIER2_CODE_PROMPT = """다음 GitHub 레포지토리 정보를 분석하여 개발자 노트를 작성하세요.
기존 주제 목록: {existing_topics}

레포지토리 정보:
{text}

규칙:
- 본문을 4~6개의 짧은 한국어 문단(paragraphs)으로 구성합니다.
- 각 문단(text)을 뒷받침할 README/설정 파일의 원문 한 줄이 있으면 verbatim으로 quote에 발췌해 넣고, 없으면 생략합니다.

JSON으로 응답하세요:
{{"title": "owner/repo — 한 줄 설명",
  "language": "ko",
  "word_count": 0, "reading_time_min": 0, "sections": [],
  "summary": "프로젝트 목적과 핵심 기능을 2~3문장으로 설명",
  "paragraphs": [
    {{"text": "한국어 문단", "quote": "원문 한 줄"}},
    {{"text": "다른 문단"}}
  ],
  "tags": ["언어", "프레임워크", "도메인키워드"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""
```

- [ ] **Step 3c: Replace `DETAILED_PROMPT`** — `services/ai/claude.py`

```python
DETAILED_PROMPT = """다음 내용을 분석하여 상세 노트를 계층 구조로 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

규칙:
- 본문을 5~12개의 의미 단위 대섹션(heading: "1. ...", "2. ...")으로 나눕니다.
- 각 대섹션은 1개 이상의 소섹션(heading: "1.1 ...")을 가지며, 각 소섹션은 2~4개의 문단형 항목(items)을 가집니다.
- 각 item은 한국어 문단 text와, 적합한 경우 원문 한 문장을 verbatim 발췌해 quote에 넣습니다. quote가 적합하지 않으면 키를 생략합니다.
- 입력 줄에 [m:ss] 형태의 타임스탬프가 있으면 섹션/소섹션의 t(섹션 시작 시각)와 item의 t(quote 시작 시각)를 초 단위 정수로 채웁니다. 타임스탬프가 없으면 t는 생략합니다.

JSON으로만 응답하세요:
{{"title": "제목", "language": "ko|en",
  "summary": "전체를 아우르는 2~3문장 한 줄 요약",
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명",
  "sections": [
    {{"heading": "1. 대주제", "t": 10, "subsections": [
      {{"heading": "1.1 소주제", "items": [
        {{"text": "한국어 문단(2~4문장)", "quote": "원문 한 문장 발췌", "t": 12}},
        {{"text": "다른 문단"}}
      ]}}
    ]}}
  ]}}
(t는 타임스탬프가 있을 때만 넣고, 없으면 키를 생략하세요.)"""
```

- [ ] **Step 3d: Wire `paragraphs` into `summarize`** — `services/ai/claude.py`

In `ClaudeProvider.summarize`, in the `SummaryResult(...)` construction, change:
```python
            key_points=data.get("key_points", []),
```
to (keep `key_points` for back-compat but also populate `paragraphs`):
```python
            key_points=data.get("key_points", []),
            paragraphs=_build_paragraphs(data),
```
Place the new line right after `key_points`. (Order in dataclass init doesn't matter; field is keyword-only.)

- [ ] **Step 3e: Mirror in `openai_provider.py`** — `services/ai/openai_provider.py`

Add `_build_paragraphs` to the existing import line (after `_build_chapters, _build_sections`):
```python
from services.ai.claude import TIER2_PROMPT, TIER2_CODE_PROMPT, TIER3_PROMPT, CHAPTERS_PROMPT, DETAILED_PROMPT, TRANSLATE_CHAPTERS_PROMPT, _build_chapters, _build_sections, _build_paragraphs
```

In `OpenAIProvider.summarize`'s `SummaryResult(...)` construction, add `paragraphs=_build_paragraphs(data),` right after `key_points=data.get("key_points", []),` (same as Claude).

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -q`
Expected: all pass (the 2 updated + 1 new openai test). If any *other* existing test (e.g. one that asserted `key_points`) still asserts the old shape, update it inline to use `paragraphs`.

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py services/ai/openai_provider.py tests/test_claude_provider.py tests/test_openai_provider.py
git commit -m "feat: prompts emit paragraphs (quick) and prose items (detailed); both providers wired"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 5: youtube 라우터 — quick도 타임스탬프 자막 + paragraphs 저장

**Files:**
- Modify: `routers/youtube.py`
- Test: `tests/test_routes_youtube.py`

- [ ] **Step 1: Add failing test** — append to `tests/test_routes_youtube.py`:

```python
@pytest.mark.asyncio
async def test_youtube_quick_passes_timestamped_transcript_and_paragraphs():
    captured = {}
    async def fake_enqueue(task, fn): captured["fn"] = fn
    fake_ai = AsyncMock(); fake_ai.name.return_value = "claude"
    from services.ai.base import SummaryResult
    fake_ai.summarize.return_value = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0, sections=[],
        summary="s", key_points=[], tags=[], suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "문단", "quote": "원문", "t": 5}],
        cost_usd=0.0, models_used=["m"])
    with patch("routers.youtube.enqueue", new=fake_enqueue), \
         patch("routers.youtube.get_provider", return_value=fake_ai), \
         patch("routers.youtube.youtube_title", new_callable=AsyncMock, return_value="제목"), \
         patch("routers.youtube.extract_youtube_full", new_callable=AsyncMock,
               return_value={"text": "PLAIN", "video_id": "v", "native_chapters": None,
                             "segments": [{"t": 0, "text": "안녕"}]}), \
         patch("routers.youtube.save_note", new_callable=AsyncMock, return_value=1) as mock_save, \
         patch("routers.youtube.record_api_cost", new_callable=AsyncMock), \
         patch("routers.youtube.resolve_chapters", new_callable=AsyncMock, return_value=([], 0.0, "")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/youtube", data={"url": "https://youtu.be/abc",
                                               "provider": "claude", "mode": "quick"})
        task = MagicMock(); task.note_id = None
        await captured["fn"](task)
    # 타임스탬프 자막을 summarize 입력으로 사용
    assert "[0:00]" in fake_ai.summarize.call_args.args[0]
    # save_note에 paragraphs 전달
    assert mock_save.call_args.kwargs.get("paragraphs") == [{"text": "문단", "quote": "원문", "t": 5}]
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_routes_youtube.py -k quick_passes_timestamped -v`
Expected: FAIL — current code passes `data["text"]` for quick (no `[0:00]`) and `save_note` is called without `paragraphs`.

- [ ] **Step 3a: Pass timestamped transcript regardless of mode** — `routers/youtube.py`

Replace the existing block in `do_work`:
```python
        if mode == "detailed" and data["segments"]:
            summarize_input = segments_to_transcript(data["segments"])
        else:
            summarize_input = data["text"]
```
with:
```python
        if data["segments"]:
            summarize_input = segments_to_transcript(data["segments"])
        else:
            summarize_input = data["text"]
```
(quick도 자막에 [m:ss]가 있으면 인용 옆 시작 시각을 얻는다.)

- [ ] **Step 3b: Pass paragraphs to save_note** — `routers/youtube.py`

In the same `do_work`, change the `save_note(...)` call to include `paragraphs=result.paragraphs`:
```python
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
            paragraphs=result.paragraphs,
        )
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_routes_youtube.py -q`
Expected: all pass (new test + existing). The existing `test_youtube_detailed_passes_timestamped_transcript` still passes because the simplified condition covers detailed too.

- [ ] **Step 5: Commit**

```bash
git add routers/youtube.py tests/test_routes_youtube.py
git commit -m "feat: youtube quick also gets timestamped transcript; persist paragraphs"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 6: 마크다운 렌더 — paragraphs + blockquote (`_make_md_content`)

**Files:**
- Modify: `services/storage.py` (`_make_md_content` only)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Update existing detailed md test + add quick paragraphs test** — `tests/test_storage.py`

Replace the body of `test_make_md_content_hierarchical` (existing) so the input uses the new `block` shape and assertions check paragraph + blockquote output:
```python
def test_make_md_content_hierarchical():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 본문 1", "quote": "원문 한 문장", "t": 90},
                {"text": "문단 본문 2"},
            ]}]}],
        summary="한 줄", key_points=[], tags=["x"], suggested_topic="AI",
        summary_mode="detailed", insights=["i"], questions_raised=["q"])
    md = _make_md_content("youtube", "u", r, "claude")
    assert "## 목차" in md
    assert "## 1. A" in md
    assert "### 1.1 B" in md
    assert "문단 본문 1" in md
    assert '> [1:30] "원문 한 문장"' in md
    assert "문단 본문 2" in md
    assert "## 인사이트" in md
    assert "## 탐구할 질문" in md
    assert "핵심 논거" not in md
    assert "\n\n\n" not in md  # 이중 빈 줄 없음
```

Append a quick paragraphs md test:
```python
def test_make_md_content_quick_paragraphs():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="요약", key_points=[], tags=[], suggested_topic="",
        summary_mode="quick",
        paragraphs=[
            {"text": "문단 A", "quote": "발췌", "t": 30},
            {"text": "문단 B"},
        ])
    md = _make_md_content("youtube", "u", r, "claude")
    assert "## 본문" in md
    assert "문단 A" in md
    assert '> [0:30] "발췌"' in md
    assert "문단 B" in md
    assert "## 핵심 포인트" not in md  # 신규 형식이므로 옛 헤더 없음
```

Add a backward-compat quick test (existing test `test_make_md_content_quick_stays_flat` still asserts `## 핵심 포인트`):
- That existing test uses `key_points=["k1"]` and `paragraphs` is default `[]` → fall-back branch renders `## 핵심 포인트`. Confirm it still passes; if not, update assertion appropriately. (No changes needed if it's already structured that way.)

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_storage.py -k make_md_content -v`
Expected: the hierarchical test FAILs (current md uses `- **lead**` not paragraph); the quick_paragraphs test FAILs (current md doesn't render `## 본문`).

- [ ] **Step 3: Rewrite the body section of `_make_md_content`** — `services/storage.py`

Replace the body branch (the `if result.sections: ... else: ...` block that ends at the appendix `_heading` helper) with this:
```python
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
                    if it.get("text"):  # 신규: 문단 + 인용
                        lines.append(it["text"])
                        if it.get("quote"):
                            ts = f"[{_ts(it['t'])}] " if "t" in it else ""
                            lines.append(f'> {ts}"{it["quote"]}"')
                    else:  # 백워드 호환: 옛 {lead, bullets}
                        ts = f" ({_ts(it['t'])})" if "t" in it else ""
                        lines.append(f"- **{it.get('lead','')}**{ts}")
                        for b in it.get("bullets", []):
                            lines.append(f"  - {b}")
                    lines.append("")
    elif result.paragraphs:  # quick 신규: 문단 본문
        lines.append("## 본문")
        lines.append("")
        for p in result.paragraphs:
            lines.append(p["text"])
            if p.get("quote"):
                ts = f"[{_ts(p['t'])}] " if "t" in p else ""
                lines.append(f'> {ts}"{p["quote"]}"')
            lines.append("")
    else:  # 백워드 호환: 옛 quick key_points
        lines.append("## 핵심 포인트")
        for p in result.key_points:
            lines.append(f"- {p}")
```
(Leave the `_heading` helper and the insights/questions blocks below it unchanged.)

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_storage.py -q`
Expected: all pass (incl. updated hierarchical + new quick_paragraphs + existing key_points fall-back).

- [ ] **Step 5: Commit**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: markdown renders paragraphs + blockquote (quick and detailed)"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 7: 모달 — paragraphs + blockquote 렌더 (quick·detailed 양쪽, 옛 데이터 폴백)

**Files:**
- Modify: `templates/partials/note_detail_modal.html`
- 검증: 브라우저 (단위 테스트 없음, 컨트롤러가 E2E 검증)

- [ ] **Step 1: Detailed 본문 — item 렌더 교체**

Find the inner `<ul class="space-y-1.5"> ... {% for it in sub["items"] %} ... </ul>` block (inside the `<details>` content). Replace it with:
```html
            <div class="space-y-3">
              {% for it in sub["items"] %}
              {% if it.text %}
              {# 신규: 문단 + 인용 #}
              <div>
                <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">{{ it.text }}</p>
                {% if it.quote %}
                <blockquote class="border-l-4 border-[#1F6F4A]/40 pl-3 mt-1.5 text-[12px] italic text-gray-600 dark:text-gray-400">
                  {% if it.t is defined and video_id %}<button type="button" onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ it.t }})" class="text-[11px] font-mono text-[#1F6F4A] dark:text-[#34A66A] hover:underline mr-1.5">⏱{{ "%d:%02d:%02d"|format(it.t // 3600, it.t % 3600 // 60, it.t % 60) if it.t >= 3600 else "%d:%02d"|format(it.t // 60, it.t % 60) }}</button>{% endif %}
                  &ldquo;{{ it.quote }}&rdquo;
                </blockquote>
                {% endif %}
              </div>
              {% else %}
              {# 백워드 호환: 옛 {lead, bullets} #}
              <div class="text-[13px] text-gray-700 dark:text-gray-300">
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
              </div>
              {% endif %}
              {% endfor %}
            </div>
```

- [ ] **Step 2: Quick 본문 — paragraphs 우선, key_points 폴백**

Find the `{% else %}` branch (currently `<!-- 핵심 포인트 (quick) -->`) and replace it with:
```html
    {% else %}
    {% set p_list = note.paragraphs if note.paragraphs is not string else (note.paragraphs | fromjson) %}
    {% if p_list %}
    <!-- 본문 (quick paragraphs) -->
    <div class="mb-4">
      <h3 class="text-[11px] font-bold uppercase tracking-widest text-[#1F6F4A] dark:text-[#34A66A] mb-2">본문</h3>
      <div class="space-y-3">
        {% for p in p_list %}
        <div>
          <p class="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">{{ p.text }}</p>
          {% if p.quote %}
          <blockquote class="border-l-4 border-[#1F6F4A]/40 pl-3 mt-1.5 text-[12px] italic text-gray-600 dark:text-gray-400">
            {% if p.t is defined and video_id %}<button type="button" onclick="ytSeek({{ p.t }})" class="text-[11px] font-mono text-[#1F6F4A] dark:text-[#34A66A] hover:underline mr-1.5">⏱{{ "%d:%02d:%02d"|format(p.t // 3600, p.t % 3600 // 60, p.t % 60) if p.t >= 3600 else "%d:%02d"|format(p.t // 60, p.t % 60) }}</button>{% endif %}
            &ldquo;{{ p.quote }}&rdquo;
          </blockquote>
          {% endif %}
        </div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    <!-- 핵심 포인트 (옛 quick) -->
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
    {% endif %}
```
(Total `{% if %}` count: outer `{% if sec_list %}` opens one; this block adds two nested `{% if %}` (p_list, kp_list) so three `{% endif %}` close them — make sure the final `{% endif %}` count matches.)

- [ ] **Step 3: Sanity render (must not raise Jinja error)**

```bash
python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print('home', c.get('/').status_code, 'detail-missing', c.get('/api/items/99999/detail').status_code)"
```
Expected: `home 200 detail-missing 200` (the 99999 path renders an empty body via `{% if note %}` guard; the key check is that it doesn't 500 from a Jinja syntax/balance error).

Also run the existing route tests:
```bash
python -m pytest tests/test_routes_items.py -q
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add templates/partials/note_detail_modal.html
git commit -m "feat: modal renders paragraphs + blockquote (quick and detailed) with old-shape fallback"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 5: Browser verify (manual, post-merge of all tasks)**

1. 서버 재시작 후 `http://localhost:8000`.
2. 한 YouTube 영상을 **quick**으로 분석 → 모달 열기: `## 본문` 위치에 짧은 문단들이 나오고, 각 문단 아래 회색 좌측 보더의 `>` blockquote(인용) 표시. youtube면 `⏱` 클릭 시 영상 이동.
3. 같은(또는 다른) YouTube를 **detailed**로 분석 → 각 H3 소섹션 아래에 문단+인용 블록이 나옴. 굵은 lead·중첩 불릿이 사라졌는지 확인.
4. 기존 노트(이전 분석본) 하나 열기 → `paragraphs`가 비어 있어도 핵심 포인트/lead+bullets 폴백으로 깨짐 없이 렌더.
5. vault 내 새 .md 파일 한 건 확인 → `## 본문`(quick) 또는 `### 1.1 …`(detailed) 아래에 문단 + `> "..."` blockquote 형식으로 저장됨.

---

## 최종 검증

- [ ] `python -m pytest -q` — 전체 통과(신규 실패 없음).
- [ ] Task 7 브라우저 검증 완료.
