# 트랜스크립트 청킹 + Map-reduce Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `text[:12000]` 자르기를 제거하고, 긴 입력은 자동으로 chunk로 나눠 LLM에 따로 호출 후 paragraphs/sections concat + 통합 summary LLM 호출(map-reduce). 39분 영상도 끝까지 다룸.

**Architecture:** `services/extractor.py::_chunk_for_llm`이 text를 줄 단위로 자른다. 양 provider(claude/openai)의 `summarize`가 길이 임계(18K) 초과 시 chunk별로 `_summarize_single` 호출 후 `_merge_partials`로 통합. `_merge_partials`는 `_renumber_sections`로 sections 번호 재부여 + `SUMMARY_MERGE_PROMPT`로 LLM 통합 summary 호출. fallback provider는 비목표.

**Tech Stack:** Anthropic + OpenAI SDK (기존), pytest. 브랜치: `feature/transcript-chunking-2026-05-31`.

---

## File Structure

**Modify:**
- `services/extractor.py` — `_chunk_for_llm` 헬퍼 추가.
- `services/ai/claude.py` — `_renumber_sections` + `SUMMARY_MERGE_PROMPT` + `_summarize_single` 추출 + `summarize` 분기 + `_merge_partials`.
- `services/ai/openai_provider.py` — `_summarize_single` 추출 + `summarize` 분기 + `_merge_partials_gpt` (claude의 LLM 호출 패턴이 달라 별도).
- `tests/test_extractor.py` — `_chunk_for_llm` 3 단위 테스트.
- `tests/test_claude_provider.py` — `_renumber_sections` 1 + summarize chunking 2 통합 테스트.
- `tests/test_openai_provider.py` — summarize chunking 1 mirror 테스트.

기존 139 → 146 (+7).

---

## Task 1: `services/extractor.py::_chunk_for_llm`

**Files:**
- Modify: `services/extractor.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: 실패 테스트 3개** — `tests/test_extractor.py` append

```python
def test_chunk_for_llm_empty_returns_empty_list():
    from services.extractor import _chunk_for_llm
    assert _chunk_for_llm("") == []
    assert _chunk_for_llm("", max_chars=10) == []


def test_chunk_for_llm_short_returns_single_chunk():
    from services.extractor import _chunk_for_llm
    text = "한 줄짜리 짧은 텍스트."
    assert _chunk_for_llm(text, max_chars=100) == [text]


def test_chunk_for_llm_splits_on_line_boundary():
    """긴 text는 줄 경계에서 잘리고, 각 chunk는 max_chars 한도 이하."""
    from services.extractor import _chunk_for_llm
    # 각 줄 ~20자, 5줄 → 총 ~100자
    lines = [f"[{i}:00] 라인 {i} 내용입니다." for i in range(5)]
    text = "\n".join(lines)
    chunks = _chunk_for_llm(text, max_chars=40)
    assert len(chunks) >= 2
    # 각 chunk는 max_chars 이하 (마지막 chunk 빼고 보장. 모든 chunk가 한 줄 이상 포함)
    for ch in chunks:
        # 한 줄이 max_chars보다 짧으므로 chunk가 그 한 줄 단위로 묶임
        assert "\n" in ch or len(ch) <= 50  # 줄 단위 묶임
    # 합치면 원본과 동일(개행 손실 없음)
    assert "\n".join(chunks) == text
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_extractor.py -k chunk_for_llm -v
```
Expected: ImportError.

- [ ] **Step 3: 헬퍼 추가** — `services/extractor.py` 맨 아래에 append

```python
def _chunk_for_llm(text: str, max_chars: int = 12000) -> list[str]:
    """text를 줄(\\n) 단위로 묶어 max_chars 한도 안의 chunk list 반환.
    빈 text는 []. 한 줄이 max_chars보다 길면 그 줄 단독 chunk(잘리지 않음).
    합쳐도 개행을 손실 없이 원본 text 복원 가능."""
    if not text:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_size = len(line) + 1  # +1 for \n
        if current and current_len + line_size > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks
```

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_extractor.py -k chunk_for_llm -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 142 passed (139 + 3).

```
git add services/extractor.py tests/test_extractor.py
git commit -m "feat: _chunk_for_llm helper splits text on line boundaries

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `services/ai/claude.py::_renumber_sections`

**Files:**
- Modify: `services/ai/claude.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_claude_provider.py` append

```python
def test_renumber_sections_resets_section_and_subsection_indices():
    """두 chunk의 sections concat 후 1, 2, 3...로 재부여, subsection M.N도 갱신."""
    from services.ai.claude import _renumber_sections
    sections = [
        {"heading": "1. A", "subsections": [
            {"heading": "1.1 x", "items": []},
            {"heading": "1.2 y", "items": []},
        ]},
        {"heading": "1. C", "subsections": [
            {"heading": "1.1 z", "items": []},
        ]},
    ]
    result = _renumber_sections(sections)
    assert result == [
        {"heading": "1. A", "subsections": [
            {"heading": "1.1 x", "items": []},
            {"heading": "1.2 y", "items": []},
        ]},
        {"heading": "2. C", "subsections": [
            {"heading": "2.1 z", "items": []},
        ]},
    ]
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_claude_provider.py -k renumber_sections -v
```
Expected: ImportError.

- [ ] **Step 3: 헬퍼 추가** — `services/ai/claude.py`, `_build_refs` 함수 직후에 append

```python
def _renumber_sections(sections: list[dict]) -> list[dict]:
    """sections의 heading prefix 'N. ...'를 1부터 재부여하고
    subsection heading 'M.N ...'의 M도 parent의 새 번호로 갱신.
    items/refs 등 다른 필드는 그대로."""
    out = []
    for new_idx, sec in enumerate(sections, start=1):
        new_sec = dict(sec)
        new_sec["heading"] = re.sub(
            r'^\d+\.\s*', f'{new_idx}. ', sec.get("heading", ""))
        if "subsections" in sec:
            new_subs = []
            for sub in sec["subsections"]:
                new_sub = dict(sub)
                new_sub["heading"] = re.sub(
                    r'^\d+\.(\d+)\s*',
                    lambda m: f'{new_idx}.{m.group(1)} ',
                    sub.get("heading", ""),
                )
                new_subs.append(new_sub)
            new_sec["subsections"] = new_subs
        out.append(new_sec)
    return out
```

(`re`는 이미 import됨 — 기존 `_parse_json` 함수가 사용 중.)

- [ ] **Step 4: 통과 확인**
```
python -m pytest tests/test_claude_provider.py -k renumber_sections -v
```
Expected: 1 passed.

- [ ] **Step 5: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 143 passed (142 + 1).

```
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: _renumber_sections renumbers section/subsection indices for chunk merge

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `_summarize_single` 추출 (claude + openai 양쪽 동시 refactor)

**Files:**
- Modify: `services/ai/claude.py`, `services/ai/openai_provider.py`

행동 변화 없는 순수 리팩토. 기존 `summarize` 메서드를 `_summarize_single`로 이름 변경하고, `summarize`는 그것을 그대로 호출하는 thin wrapper로 둠.

- [ ] **Step 1: `services/ai/claude.py` — summarize 추출**

기존 `summarize` 메서드 본문을 그대로 `_summarize_single`로 옮기고, `summarize`는 위임:

기존:
```python
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        ...
        return result
```

신규 (두 메서드로 분리):
```python
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        return await self._summarize_single(text, source_type, mode, existing_topics)

    async def _summarize_single(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used: list[str] = []

        model = config.CLAUDE_MODELS["tier2"]
        if mode == "detailed":
            template = DETAILED_PROMPT
            max_tokens = 8192
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
            max_tokens = 4096
        prompt = template.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
        total_cost += _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        models_used.append(model)

        data = _parse_json(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=_build_sections(data),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            paragraphs=_build_paragraphs(data),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._run_tier3(result, total_cost, models_used)

        return result
```

- [ ] **Step 2: `services/ai/openai_provider.py` — summarize 추출 (같은 패턴)**

기존 `summarize` 본문을 `_summarize_single`로 옮기고, `summarize`는 위임:
```python
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        return await self._summarize_single(text, source_type, mode, existing_topics)

    async def _summarize_single(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used: list[str] = []
        model = config.GPT_MODELS["tier2"]

        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
        prompt = template.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        total_cost += _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        models_used.append(model)

        if raw is None:
            raise ValueError(f"GPT가 빈 응답을 반환했습니다(model={model}, finish_reason={resp.choices[0].finish_reason})")
        data = json.loads(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=_build_sections(data),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            paragraphs=_build_paragraphs(data),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._gpt_tier3(result, total_cost, models_used)

        return result
```

- [ ] **Step 3: 회귀 확인 — 모든 기존 테스트 통과해야**
```
python -m pytest -q
```
Expected: 143 passed (변경 없음 — 순수 리팩토).

- [ ] **Step 4: 커밋**
```
git add services/ai/claude.py services/ai/openai_provider.py
git commit -m "refactor: extract _summarize_single from summarize (claude + openai)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `SUMMARY_MERGE_PROMPT` + `_merge_partials` (claude + openai)

**Files:**
- Modify: `services/ai/claude.py`, `services/ai/openai_provider.py`

- [ ] **Step 1: `services/ai/claude.py` — prompt + merge helper 추가**

`DETAILED_PROMPT` 뒤에 추가:
```python
SUMMARY_MERGE_PROMPT = """다음은 한 영상을 여러 조각으로 나눠 분석한 부분 요약들입니다.
이를 합쳐 영상 전체를 자연스럽게 다루는 한국어 2~3문장 통합 요약을 작성하세요.

부분 요약:
{partials}

JSON으로만 응답하세요:
{{"summary": "2~3문장 한국어 통합 요약"}}"""
```

`ClaudeProvider` 클래스 안 `_summarize_single` 뒤에 추가 (logger 사용을 위해 파일 상단에 `import logging` + `log = logging.getLogger(__name__)` 없으면 추가):
```python
    async def _merge_partials(
        self,
        partials: list[SummaryResult],
        mode: str,
    ) -> SummaryResult:
        """여러 SummaryResult를 1개로 병합. summary는 LLM 통합 호출."""
        base = partials[0]

        all_paragraphs = [p for prt in partials for p in (prt.paragraphs or [])]
        all_sections = _renumber_sections(
            [s for prt in partials for s in (prt.sections or [])]
        )
        all_insights: list[str] = []
        for prt in partials:
            if prt.insights:
                all_insights.extend(prt.insights)
        all_questions: list[str] = []
        for prt in partials:
            if prt.questions_raised:
                all_questions.extend(prt.questions_raised)
        all_key_points = [k for prt in partials for k in (prt.key_points or [])]
        all_tags = list({t for prt in partials for t in (prt.tags or [])})
        total_cost = sum(prt.cost_usd for prt in partials)
        models_used: list[str] = []
        for prt in partials:
            models_used.extend(prt.models_used or [])

        merged_summary = base.summary
        try:
            partials_text = "\n\n".join(
                f"[조각 {i+1}] {prt.summary}" for i, prt in enumerate(partials) if prt.summary
            )
            if partials_text:
                model = config.CLAUDE_MODELS["tier2"]
                merge_resp = await self._client.messages.create(
                    model=model,
                    max_tokens=512,
                    messages=[{"role": "user", "content": SUMMARY_MERGE_PROMPT.format(partials=partials_text)}],
                )
                merge_raw = merge_resp.content[0].text
                merge_data = _parse_json(merge_raw)
                merged_summary = merge_data.get("summary", base.summary)
                total_cost += _calc_cost(model, merge_resp.usage.input_tokens, merge_resp.usage.output_tokens)
                models_used.append(model)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"summary merge failed, using first partial: {e}")

        return SummaryResult(
            title=base.title,
            language=base.language,
            word_count=sum(prt.word_count for prt in partials),
            reading_time_min=sum(prt.reading_time_min for prt in partials),
            sections=all_sections,
            summary=merged_summary,
            key_points=all_key_points,
            tags=all_tags,
            suggested_topic=base.suggested_topic,
            summary_mode=mode,
            insights=all_insights or None,
            questions_raised=all_questions or None,
            paragraphs=all_paragraphs,
            cost_usd=total_cost,
            models_used=models_used,
        )
```

- [ ] **Step 2: `services/ai/openai_provider.py` — `_merge_partials` 추가 (같은 패턴, OpenAI client)**

`OpenAIProvider` 클래스 안 `_summarize_single` 뒤에 추가:
```python
    async def _merge_partials(
        self,
        partials: list[SummaryResult],
        mode: str,
    ) -> SummaryResult:
        """여러 SummaryResult를 1개로 병합. summary는 LLM 통합 호출."""
        from services.ai.claude import SUMMARY_MERGE_PROMPT, _renumber_sections
        base = partials[0]

        all_paragraphs = [p for prt in partials for p in (prt.paragraphs or [])]
        all_sections = _renumber_sections(
            [s for prt in partials for s in (prt.sections or [])]
        )
        all_insights: list[str] = []
        for prt in partials:
            if prt.insights:
                all_insights.extend(prt.insights)
        all_questions: list[str] = []
        for prt in partials:
            if prt.questions_raised:
                all_questions.extend(prt.questions_raised)
        all_key_points = [k for prt in partials for k in (prt.key_points or [])]
        all_tags = list({t for prt in partials for t in (prt.tags or [])})
        total_cost = sum(prt.cost_usd for prt in partials)
        models_used: list[str] = []
        for prt in partials:
            models_used.extend(prt.models_used or [])

        merged_summary = base.summary
        try:
            partials_text = "\n\n".join(
                f"[조각 {i+1}] {prt.summary}" for i, prt in enumerate(partials) if prt.summary
            )
            if partials_text:
                model = config.GPT_MODELS["tier2"]
                merge_resp = await self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": SUMMARY_MERGE_PROMPT.format(partials=partials_text)}],
                    response_format={"type": "json_object"},
                )
                merge_raw = merge_resp.choices[0].message.content
                if merge_raw:
                    merge_data = json.loads(merge_raw)
                    merged_summary = merge_data.get("summary", base.summary)
                total_cost += _calc_cost(model, merge_resp.usage.prompt_tokens, merge_resp.usage.completion_tokens)
                models_used.append(model)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"summary merge failed, using first partial: {e}")

        return SummaryResult(
            title=base.title,
            language=base.language,
            word_count=sum(prt.word_count for prt in partials),
            reading_time_min=sum(prt.reading_time_min for prt in partials),
            sections=all_sections,
            summary=merged_summary,
            key_points=all_key_points,
            tags=all_tags,
            suggested_topic=base.suggested_topic,
            summary_mode=mode,
            insights=all_insights or None,
            questions_raised=all_questions or None,
            paragraphs=all_paragraphs,
            cost_usd=total_cost,
            models_used=models_used,
        )
```

- [ ] **Step 3: 회귀 확인 + 커밋** (이 task의 단위 테스트는 다음 task에서 통합 테스트로 검증)
```
python -m pytest -q
```
Expected: 143 passed (변경 없음 — merge는 아직 호출되지 않음).

```
git add services/ai/claude.py services/ai/openai_provider.py
git commit -m "feat: SUMMARY_MERGE_PROMPT + _merge_partials helpers (claude + openai)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `summarize`에 chunking 분기 추가 + 통합 테스트

**Files:**
- Modify: `services/ai/claude.py`, `services/ai/openai_provider.py`
- Test: `tests/test_claude_provider.py`, `tests/test_openai_provider.py`

- [ ] **Step 1: 실패 테스트 — `tests/test_claude_provider.py` append**

```python
@pytest.mark.asyncio
async def test_summarize_short_text_uses_single_call(provider):
    """text 길이가 18K 미만이면 _summarize_single 1회만 호출 (chunking 안 함)."""
    import json
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "요약",
        "paragraphs": [{"text": "문단", "refs": []}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp) as mock_create:
        res = await provider.summarize("짧은 텍스트", "youtube", "quick", [])
    assert mock_create.call_count == 1
    assert res.paragraphs == [{"text": "문단", "refs": []}]


@pytest.mark.asyncio
async def test_summarize_long_text_chunks_and_merges(provider):
    """text가 18K 초과면 chunk별 호출 + merge LLM 호출."""
    import json
    # 18K 초과 input (한 줄 ~3K씩 7줄 = ~21K)
    long_text = "\n".join([f"[{i}:00] " + ("가" * 3000) for i in range(7)])

    chunk_resp = MagicMock()
    chunk_resp.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "부분 요약",
        "paragraphs": [{"text": "문단", "refs": []}],
        "tags": ["x"], "suggested_topic": "AI",
    }, ensure_ascii=False))]
    chunk_resp.usage = MagicMock(input_tokens=10, output_tokens=10)

    merge_resp = MagicMock()
    merge_resp.content = [MagicMock(text=json.dumps({
        "summary": "통합된 한 줄 요약입니다.",
    }, ensure_ascii=False))]
    merge_resp.usage = MagicMock(input_tokens=5, output_tokens=5)

    with patch.object(provider._client.messages, "create",
                      new_callable=AsyncMock,
                      side_effect=[chunk_resp, chunk_resp, merge_resp]) as mock_create:
        res = await provider.summarize(long_text, "youtube", "quick", [])
    assert mock_create.call_count >= 3  # 최소 2 chunks + 1 merge
    assert res.summary == "통합된 한 줄 요약입니다."
    assert len(res.paragraphs) >= 2  # chunk 수 만큼 concat


@pytest.mark.asyncio
async def test_summarize_chunked_falls_back_when_merge_fails(provider):
    """merge LLM 호출이 실패하면 partials[0].summary로 fallback."""
    import json
    long_text = "\n".join([f"[{i}:00] " + ("가" * 3000) for i in range(7)])

    chunk_resp = MagicMock()
    chunk_resp.content = [MagicMock(text=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "첫 partial 요약",
        "paragraphs": [{"text": "문단", "refs": []}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False))]
    chunk_resp.usage = MagicMock(input_tokens=10, output_tokens=10)

    with patch.object(provider._client.messages, "create",
                      new_callable=AsyncMock,
                      side_effect=[chunk_resp, chunk_resp, Exception("merge fail")]):
        res = await provider.summarize(long_text, "youtube", "quick", [])
    assert res.summary == "첫 partial 요약"
```

`tests/test_openai_provider.py` mirror 테스트 append:
```python
@pytest.mark.asyncio
async def test_openai_summarize_long_text_chunks_and_merges(provider):
    import json
    long_text = "\n".join([f"[{i}:00] " + ("가" * 3000) for i in range(7)])

    chunk_resp = MagicMock()
    chunk_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "T", "language": "ko", "word_count": 100, "reading_time_min": 1,
        "sections": [], "summary": "부분",
        "paragraphs": [{"text": "문단", "refs": []}],
        "tags": [], "suggested_topic": "",
    }, ensure_ascii=False)))]
    chunk_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10)

    merge_resp = MagicMock()
    merge_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "summary": "통합 요약",
    }, ensure_ascii=False)))]
    merge_resp.usage = MagicMock(prompt_tokens=5, completion_tokens=5)

    with patch.object(provider._client.chat.completions, "create",
                      new_callable=AsyncMock,
                      side_effect=[chunk_resp, chunk_resp, merge_resp]) as mock_create:
        res = await provider.summarize(long_text, "youtube", "quick", [])
    assert mock_create.call_count >= 3
    assert res.summary == "통합 요약"
```

- [ ] **Step 2: 실패 확인**
```
python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -k "summarize_short or summarize_long or chunked_falls_back" -v
```
Expected: long/chunked 테스트 FAIL (mock_create.call_count == 1만 호출됨 — chunking 안 함).

- [ ] **Step 3: `services/ai/claude.py::summarize` 갱신**

```python
CHUNK_THRESHOLD = 18000

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        if len(text) <= CHUNK_THRESHOLD:
            return await self._summarize_single(text, source_type, mode, existing_topics)
        # chunking
        from services.extractor import _chunk_for_llm
        chunks = _chunk_for_llm(text)
        partials: list[SummaryResult] = []
        for chunk in chunks:
            try:
                partial = await self._summarize_single(chunk, source_type, mode, existing_topics)
                partials.append(partial)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"chunk {len(partials)+1} failed: {e}")
        if not partials:
            raise ValueError("청킹 분석 실패: 모든 chunk 호출 실패")
        return await self._merge_partials(partials, mode)
```

`CHUNK_THRESHOLD = 18000`은 파일 상단(`CLAUDE_PRICING` 옆 등 모듈 레벨)에 정의.

- [ ] **Step 4: `services/ai/openai_provider.py::summarize` 갱신 (같은 패턴)**

```python
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        from services.ai.claude import CHUNK_THRESHOLD
        if len(text) <= CHUNK_THRESHOLD:
            return await self._summarize_single(text, source_type, mode, existing_topics)
        from services.extractor import _chunk_for_llm
        chunks = _chunk_for_llm(text)
        partials: list[SummaryResult] = []
        for chunk in chunks:
            try:
                partial = await self._summarize_single(chunk, source_type, mode, existing_topics)
                partials.append(partial)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"chunk {len(partials)+1} failed: {e}")
        if not partials:
            raise ValueError("청킹 분석 실패: 모든 chunk 호출 실패")
        return await self._merge_partials(partials, mode)
```

- [ ] **Step 5: 통과 확인**
```
python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -k "summarize_short or summarize_long or chunked_falls_back" -v
```
Expected: 4 passed (3 claude + 1 openai).

- [ ] **Step 6: 전체 회귀 + 커밋**
```
python -m pytest -q
```
Expected: 147 passed (143 + 4).

```
git add services/ai/claude.py services/ai/openai_provider.py tests/test_claude_provider.py tests/test_openai_provider.py
git commit -m "feat: summarize auto-chunks long text and merges with summary LLM call

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: 브라우저 E2E 검증 (수동)

**Files:** 없음

- [ ] **Step 1: 서버 재시작 (ffmpeg PATH 포함)**

```bash
# 기존 uvicorn 종료
export PATH="$PATH:/c/Users/<username>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build/bin"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: 짧은 영상 회귀 검증 (~5분)**

브라우저 `http://localhost:8000` → 5분짜리 YouTube 영상 분석.
- 노트가 정상 생성. paragraphs 끝 시각이 영상 끝 근처.
- DB 확인: `python -c "import sqlite3; r=sqlite3.connect('liby.db').execute('SELECT id, json_array_length(paragraphs), summary FROM items ORDER BY id DESC LIMIT 1').fetchone(); print(r)"` — paragraphs 4~6개, summary 1개 (chunking 안 일어남).

- [ ] **Step 3: 39분 영상 재분석**

같은 영상 "자녀를 위한 투자 포트폴리오..."를 다시 빠른 정리로 분석.
- 진행 메시지: "AI 분석 중..." (chunking 내부 동작, 사용자 가시화 없음).
- 분석 시간이 짧은 영상보다 3~4배 길 것 (~60~90초).

- [ ] **Step 4: 결과 검증**

```bash
python -c "
import sqlite3, json
c = sqlite3.connect('liby.db')
r = c.execute('SELECT id, title, summary FROM items ORDER BY id DESC LIMIT 1').fetchone()
print('id:', r[0], 'title:', r[1])
print('summary:', r[2])
sec = json.loads(c.execute('SELECT sections FROM items WHERE id=?', (r[0],)).fetchone()[0])
pgs = json.loads(c.execute('SELECT paragraphs FROM items WHERE id=?', (r[0],)).fetchone()[0])
print('sections:', len(sec))
for s in sec[:3]:
    print(' ', s['heading'])
print('paragraphs:', len(pgs))
last_t = pgs[-1].get('refs', [{}])[-1].get('t') if pgs and pgs[-1].get('refs') else None
print('last paragraph last ref t:', last_t, 's =', (last_t or 0) // 60, '분')
"
```

확인:
- `summary`가 영상 전체를 다루는 자연스러운 통합 문장 (조각별 join 아님).
- `paragraphs`가 영상 끝(~37~38분 = 2200초+)까지 ref t를 가짐.
- detailed인 경우 sections 번호가 1, 2, 3, ..., N으로 정상 (chunk 경계에서 1로 리셋되지 않음).

- [ ] **Step 5: 모달/read view 확인**

- 카드 클릭 → 모달 → paragraph 끝 첨자가 영상 끝까지 분포.
- 📖 클릭 → read view에서도 동일.

검증 완료 시 Plan 종료.
