# 트랜스크립트 청킹 + Map-reduce 병합 (2026-05-31)

긴 입력(현재 `text[:12000]` 자르기로 약 13분 영상까지만 분석됨)을 자동으로 chunk로 나누고, 각 chunk를 같은 prompt로 LLM에 보내 partial 결과를 받고, 마지막에 별도 LLM 호출로 통합 summary를 만드는 map-reduce 패턴. 39분 영상도 전체를 다룸.

**대상 분량:** M~L (구현 사이클 1회, 단일 plan)
**테스트 카운트 변동 예상:** +6 내외
**비용 영향:** 긴 영상 1편당 약 30% 증가 (3 chunk + 1 merge = 4 LLM 호출)

---

## 동기
- 현재 `services/ai/claude.py::summarize`와 `openai_provider.py::summarize`가 `text[:12000]`로 입력을 자름.
- 39분 영상 transcript는 약 31,557자 → 약 38%만 LLM에 입력 → 노트가 13분에서 끊김.
- 단순히 자르기 한도만 늘리면 80K, 200K 영상에서 다시 한계. 청킹이 정답.
- 사용자가 map-reduce(B안) 선택: 통합 summary가 영상 전체를 자연스럽게 다룸.

---

## 핵심 결정 사항 (브레인스토밍 합의)

| 항목 | 결정 |
|---|---|
| 병합 전략 | Map-reduce — chunk별 partial + 최종 LLM 통합 summary 호출 |
| 적용 범위 | quick + detailed 모두, source 무관(YouTube/PDF/Text/Code 자동) |
| 임계값 | `len(text) <= 18000` 시 단일 호출(기존), 초과 시 청킹 |
| chunk 크기 | 약 12,000자 (실 chunk는 segment 경계 보존이라 ±2K 변동) |
| segments 청킹 | 시간 경계 보존하는 신규 `chunk_segments` 헬퍼 |
| sections 번호 | chunk 경계에서 자동 재부여(`1. A`, `2. B` / `1. C` → `3. C`) |
| 비용 누적 | 기존 `record_api_cost` 누적 패턴 그대로 (단일 노트에 여러 호출 누적) |

---

## 아키텍처 / 데이터 흐름

```
text (예: 31K자, segments_to_transcript 결과)
  ↓
summarize(text, source_type, mode, ...)
  ↓
if len(text) <= 18000:                # 짧으면 기존 path
    return _summarize_single(text, ...)
else:                                   # 길면 chunking
    chunks = chunk_text_for_llm(text)   # ['[0:00] ...', '[12:30] ...', '[25:00] ...']
    partials = [await _summarize_single(c, ...) for c in chunks]  # 3개 SummaryResult
    return _merge_partials(partials, mode, ...)  # paragraphs concat + sections renumber + merge summary LLM 호출
```

YouTube 분석에서 `summarize`로 들어가는 input은 `segments_to_transcript(data["segments"])` 결과(`[m:ss] text\n[m:ss] text\n...`) — 청킹 전에 segments 시간 경계 보존이 중요.

---

## 컴포넌트

### 신규: `services/ai/claude.py::SUMMARY_MERGE_PROMPT`
chunk summaries → 통합 한 줄 요약(2~3문장):
```python
SUMMARY_MERGE_PROMPT = """다음은 한 영상을 여러 조각으로 나눠 분석한 부분 요약들입니다.
이를 합쳐 영상 전체를 자연스럽게 다루는 한국어 2~3문장 요약을 작성하세요.

부분 요약:
{partials}

JSON으로만 응답하세요:
{{"summary": "2~3문장 한국어 통합 요약"}}"""
```

### 신규: `services/ai/claude.py::_merge_partials`
**책임:** 여러 SummaryResult를 하나로 병합.

```python
async def _merge_partials(
    partials: list[SummaryResult],
    mode: str,
    client,
    model: str,
    total_cost_ref: list,  # mutable for in-place accumulation
    models_used: list[str],
) -> SummaryResult:
    """첫 partial을 base로 paragraphs/sections concat + sections renumber + summary는 LLM merge."""
```

내부:
- `base = partials[0]`로 시작 (title/tags/suggested_topic 그대로)
- paragraphs: `result.paragraphs = sum([p.paragraphs for p in partials], [])`
- sections: chunk별 sections concat + `_renumber_sections(sections)` 호출
- insights/questions_raised: 모든 partial의 list concat (detailed only)
- summary: LLM 호출 → 모든 partial summary를 join해서 SUMMARY_MERGE_PROMPT에 넣고 호출
- 비용 누적 (`total_cost_ref`에 merge 호출 비용 add)

### 신규: `services/ai/claude.py::_renumber_sections`
```python
def _renumber_sections(sections: list[dict]) -> list[dict]:
    """sections의 heading prefix '1. ...', '2. ...'를 1부터 재부여하고
    subsection heading 'M.N ...'의 M도 parent의 새 번호로 갱신.

    예: [{heading: '1. A', subsections: [{heading: '1.1 x'}, {heading: '1.2 y'}]},
         {heading: '1. C', subsections: [{heading: '1.1 z'}]}]
     → [{heading: '1. A', subsections: [{heading: '1.1 x'}, {heading: '1.2 y'}]},
        {heading: '2. C', subsections: [{heading: '2.1 z'}]}]"""
```

regex 구현 요지:
- section heading: `re.sub(r'^\d+\.\s*', f'{new_idx}. ', heading)`
- subsection heading: `re.sub(r'^\d+\.(\d+)\s*', lambda m: f'{new_idx}.{m.group(1)} ', heading)`

### 기존 수정: `summarize` 분기
양 provider의 `summarize` 함수 시작점:
```python
if len(text) <= CHUNK_THRESHOLD:
    # 기존 코드 그대로 (단일 호출)
    ...
else:
    # 신규 chunking path
    chunks = self._chunk_for_llm(text)
    partials = []
    for chunk in chunks:
        # 기존 single-call 로직을 helper로 추출해 재사용
        partial = await self._summarize_single(chunk, source_type, mode, existing_topics)
        partials.append(partial)
    return await self._merge_partials(partials, mode)
```

기존 단일 호출 로직은 `_summarize_single`로 추출 (refactor) — 청킹과 단일 path가 같은 코드 재사용.

### `_chunk_for_llm(text)` 헬퍼
**책임:** text가 `[m:ss] ...\n[m:ss] ...\n...` 형식이면 줄(=segment) 경계 보존, 일반 텍스트면 paragraph 경계(`\n\n`) 보존.

```python
def _chunk_for_llm(text: str, max_chars: int = 12000) -> list[str]:
    """줄 단위로 누적해 max_chars 한도 안에서 chunk. 한 줄이 max_chars보다 길면 단독 chunk."""
```

YouTube의 segments_to_transcript는 줄(\n) 기준, PDF/Text는 paragraph(\n\n) 기준이지만, 줄 단위로 충분 — paragraph 끝도 `\n\n`이 `\n` + `\n`이라 줄 단위 처리에 자연스럽게 포함.

---

## 결과 병합 정책

| 필드 | 정책 |
|---|---|
| `title` | partials[0].title (첫 chunk에 영상 제목 가장 잘 나옴) |
| `language` | partials[0].language |
| `word_count` | sum |
| `reading_time_min` | sum |
| `sections` | chunk별 sections concat + `_renumber_sections` |
| `summary` | LLM merge 호출 결과 (실패 시 partials[0].summary fallback) |
| `key_points` | concat (back-compat용) |
| `paragraphs` | concat (시간 순서 보존됨) |
| `tags` | concat 후 dedupe (set) |
| `suggested_topic` | partials[0].suggested_topic |
| `summary_mode` | mode (그대로) |
| `insights` | concat (None 무시) |
| `questions_raised` | concat (None 무시) |
| `cost_usd` | 누적 (모든 chunk + merge 호출) |
| `models_used` | 누적 (중복 OK — 모니터링용) |

---

## 데이터 모델
변경 없음. `SummaryResult` 그대로. 청킹은 summarize 안에서 일어남.

---

## 에러 처리
- 한 chunk LLM 호출 실패: 예외 무시하고 빈 SummaryResult 추가 (paragraphs/sections 빈 list). 다른 chunk는 진행.
- 모든 chunk 실패: `ValueError("청킹 분석 실패")` raise.
- merge LLM 호출 실패: `partials[0].summary` fallback (degraded — 첫 chunk summary만).
- 빈 input text: chunking 안 함 — 단일 호출에서 처리.

---

## 테스트

### 단위
- `tests/test_extractor.py::test_chunk_for_llm_empty_returns_empty_list`
- `tests/test_extractor.py::test_chunk_for_llm_short_returns_single`
- `tests/test_extractor.py::test_chunk_for_llm_splits_on_line_boundary`
- `tests/test_claude_provider.py::test_renumber_sections_resets_section_and_subsection_indices`

### 통합
- `tests/test_claude_provider.py::test_summarize_short_text_uses_single_call`: text < 18K → mock create 1회.
- `tests/test_claude_provider.py::test_summarize_long_text_chunks_and_merges`: text > 18K + 3 chunk → mock create 4회(3 partial + 1 merge), 결과 paragraphs concat + sections renumber + summary가 merge 응답.
- `tests/test_claude_provider.py::test_summarize_chunked_falls_back_when_merge_fails`: merge 호출 예외 → summary = partials[0].summary.

---

## Non-goals
- detailed sections 중복 통합 (chunk 1 "도입"과 chunk 2 "서론" 합치기) — LLM 판단 어려움, 단순 concat + renumber만.
- 모델별 context 한도 자동 감지 (claude 200K, gpt-4o 128K). 고정 임계값.
- 부분 결과 caching (chunk 별 응답 캐싱).
- 청킹 시 progress 단계별 노출 ("3 중 2번째 분석 중..."). 진행 메시지는 그대로 "AI 분석 중...".
- Chunking-specific prompt (예: "당신은 영상의 N번째 부분을 분석합니다"). 같은 prompt 사용.

---

## 외부 의존성
신규 의존 없음 (yt-dlp, anthropic, openai SDK 그대로).

---

## 검증 (E2E)
1. `python -m pytest -q` — 새 테스트 통과.
2. 짧은 영상(5~10분) 분석 → 기존처럼 단일 호출, 동작 동일.
3. 39분 영상(`자녀 투자 포트폴리오`) 재분석 → 노트가 영상 끝까지 다룸. paragraphs 마지막 ref.t가 영상 끝(~37~38분) 근처. sections heading이 1, 2, ..., N으로 정상 번호.
4. summary가 전체 영상을 자연스럽게 다룸(부분 요약 join이 아닌 통합 문장).
5. 비용 누적 — record_api_cost 호출 횟수 = chunk수 + 1.
