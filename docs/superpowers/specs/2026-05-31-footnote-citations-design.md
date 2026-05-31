# 각주 + 전체 화면 Read View (2026-05-31)

YouTube 노트의 paragraph/item 본문 끝에 `[1][2][3]` 첨자 형태 각주를 두고, 클릭 시 영상을 해당 시각으로 점프. 전체 화면 read view에서는 좌측에 영상 + 트랜스크립트 패널이 보이고, 각주 클릭 시 영상 + 트랜스크립트가 함께 해당 위치로 이동. Lilys AI 스타일.

**대상 분량:** L (구현 사이클 1회, 단일 plan, 8 task 내외)
**테스트 카운트 변동 예상:** +10 내외

---

## 동기
- 현재 paragraph에는 quote 1개 + ⏱ 버튼 — 시각 연결 1:1.
- Lilys는 paragraph마다 여러 각주 → 더 촘촘한 영상·텍스트 백링크.
- 트랜스크립트 패널을 함께 보면 AI 요약과 원본 자막을 한눈에 대조 가능 → 사용자가 직접 사실 확인.

---

## 핵심 결정 사항 (브레인스토밍 합의)

| 항목 | 결정 |
|---|---|
| Read view 형태 | 별도 전체 화면 (`/items/{id}/read`) — 모달이 아닌 새 페이지 |
| 모달 운명 | 기존 모달 유지 + 우상단에 "📖 전체 화면 보기" 버튼 추가 |
| 각주 데이터 모델 | paragraph/item에 `refs: [{t, snippet?}, ...]` 추가, 기존 `quote+t` 제거(자연스럽게 `refs[0]`이 그 역할) |
| 마커 위치 | paragraph 끝에 `[1][2][3]` 첨자 (문장 중간 inline 마커 X) |
| 적용 범위 | YouTube quick paragraphs + detailed sections.subsections.items 모두 |
| 트랜스크립트 저장 | `items.transcript_segments TEXT` 컬럼 추가, segments JSON 저장 |
| 비-YouTube | read view 비활성화 — 기존 모달만 사용 |

---

## 아키텍처 / 데이터 흐름

```
analyze_youtube(do_work):
  data = extract_youtube_full(url)  # 이미 segments 받음
  result = ai.summarize(...)        # 신규 refs 포함된 paragraphs/items
  chapters = resolve_chapters(...)
  chapters = capture_chapter_screenshots(...)  # 기존
  save_note(..., timeline=chapters, segments=data["segments"])  # ← segments 추가
```

```
사용자 흐름:
카드 클릭 → 기존 모달 (refs 첨자 노출)
모달 우상단 "📖" 클릭 → 새 탭/창에서 /items/{id}/read
read view → 좌측 영상 + 트랜스크립트, 우측 본문 + refs
refs 클릭 → ytSeek(t) + 트랜스크립트 해당 segment 스크롤·highlight
```

---

## 데이터 모델

### paragraph/item 확장
```jsonc
{
  "text": "한국어 문단 본문(2~4문장)",
  "refs": [
    {"t": 30, "snippet": "verbatim 원문 한 문장"},
    {"t": 65, "snippet": "또 다른 원문"}
  ]
}
```
- `refs`는 list — 비어 있으면 첨자 안 보임.
- `snippet`은 optional — read view 트랜스크립트 hover 툴팁 또는 모달 fallback에 사용.
- `t`는 초 단위 정수.

### `quote/t` 필드 정리
- `SummaryResult`/`_build_paragraphs`/`_build_sections`: `quote/t` 빌드 로직 제거 → `refs` 빌드만.
- 데이터 마이그레이션: **없음**. 옛 노트의 `{text, quote, t}` paragraphs는 그대로 DB에 남음. 렌더에서 `refs`가 비고 `quote`가 있으면 `[{t, snippet: quote}]`로 동적 변환(읽기 전용 fallback).

### DB 컬럼 추가
- `items.transcript_segments TEXT` (JSON `[{t, text}, ...]`)
- `_ensure_column(db, "transcript_segments", "TEXT")` 멱등.
- `_JSON_FIELDS`에 `"transcript_segments"` 추가 → `get_note`가 자동 deserialize.
- `save_note(segments: list | None = None)` 파라미터 추가. INSERT에 1 컬럼·1 값 추가.

---

## 컴포넌트

### LLM Prompt 갱신 (`services/ai/claude.py`)
- `TIER2_PROMPT`: paragraph 출력 스키마 변경:
  - 기존 `{"text": "...", "quote": "...", "t": 30}` → 신규 `{"text": "...", "refs": [{"t": 30, "snippet": "..."}, {"t": 65, "snippet": "..."}]}`
  - 규칙: 각 paragraph마다 1~3개의 refs (해당 문단을 뒷받침하는 원문 발췌 + 시작 시각).
- `TIER2_CODE_PROMPT`: refs 없음 (코드 소스는 시각 무관) — paragraph만 유지.
- `DETAILED_PROMPT`: item도 동일한 refs 구조로 변경.

### `_build_paragraphs` / `_build_sections` (`services/ai/claude.py`)
- 신규 `_build_refs(refs_raw: list) -> list[dict]` 헬퍼 — `[{t, snippet?}]` 빌드. `_to_t` 가드 재사용, 잘못된 dict/빈 t 항목 skip.
- `_build_paragraphs`/`_build_sections` 내부: `quote`/`t` 빌드 분기 제거, `refs=_build_refs(p.get("refs", []))` 호출.

### `services/storage.py`
- `_JSON_FIELDS`에 `"transcript_segments"` 추가.
- `save_note` 시그니처: `segments: list | None = None` 마지막에 추가.
- INSERT 컬럼/값 1개 추가(transcript_segments). 카운트 18 → 19.
- `upgrade_to_detailed`은 그대로 (segments는 분석 시점에만 저장).

### `routers/youtube.py`
- `analyze_youtube` do_work에서 `save_note(..., segments=data["segments"])` 한 줄 추가.

### `routers/items.py` 신규 라우트
```python
@router.get("/{note_id}/read")
async def read_view(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note or note.get("type") != "youtube":
        # non-YouTube는 read view 없음 — 메인으로 redirect
        return RedirectResponse("/")
    video_id = youtube_video_id(note.get("source_url"))
    return templates.TemplateResponse(
        request, "read.html", {"note": note, "video_id": video_id},
    )
```

### 신규 템플릿 `templates/read.html`
- `base.html` 확장 (navbar/sidebar 유지)
- 메인 영역 좌우 분할 (`md:grid md:grid-cols-5 md:gap-4`):
  - **좌측 (2/5)**:
    - `<div class="sticky top-0">` 영상 iframe + `data-video-id`
    - 트랜스크립트 패널: `<ul>` 안 각 segment를 `<li onclick="ytSeek(s.t)" data-t="{{ s.t }}">[m:ss] {{ s.text }}</li>` 형태. 현재 영상 시각 기반 highlight는 follow-up(spec V1은 클릭만).
  - **우측 (3/5)**:
    - paragraph/item 본문 — 모달과 동일한 렌더 (paragraphs 또는 sections 분기)
    - paragraph 끝에 `{{ ref_chips(p.refs, video_id) }}` 매크로로 `[1][2][3]` 첨자
- JS:
  - `ytSeek(t)`는 base.html에 이미 정의됨 (모달용). read view에서 동일 사용 가능 → base.html의 player 초기화 로직 read view에서도 재사용. video iframe id를 `yt-player`로 동일하게 두면 됨.
  - 트랜스크립트 highlight는 follow-up.

### 모달 변경 (`templates/partials/note_detail_modal.html`)
- 우상단 ✕ 버튼 옆에 `<a href="/items/{{ note.id }}/read" target="_blank">📖</a>` 추가 (YouTube만 표시).
- 모달 본문 paragraph 끝 첨자 노출 — read view와 동일 매크로 `ref_chips` 호출.

### Jinja 매크로 `templates/macros.html` (신규)
모달과 read view 양쪽에서 `{% from "macros.html" import ref_chips %}`로 import. 단일 정의:
```jinja
{% macro ref_chips(refs, video_id) %}
{% if refs and video_id %}
<span class="inline-flex gap-1 ml-1 align-super">
  {% for r in refs %}
  <button type="button"
          onclick="event.stopPropagation(); ytSeek({{ r.t }})"
          title="{{ r.snippet }}"
          class="text-[10px] px-1 bg-[#EAF4EE] text-[#1F6F4A] hover:bg-[#1F6F4A] hover:text-white rounded transition-colors">{{ loop.index }}</button>
  {% endfor %}
</span>
{% endif %}
{% endmacro %}
```

---

## 백워드 호환
- 옛 노트(refs 없는 paragraphs `{text, quote, t}`):
  - **변환 위치**: 템플릿 안 Jinja 표현(데이터는 DB에 그대로 보관, 마이그레이션 없음).
  - 매크로 호출 전에 fallback list 계산: `{% set effective = p.refs if p.refs else ([{"t": p.t, "snippet": p.quote}] if p.quote is defined else []) %}` 후 `{{ ref_chips(effective, video_id) }}`.
  - 결과: 옛 노트도 `[1]` 첨자 1개로 표시됨, snippet hover 가능.
- 옛 detailed items(`{lead, bullets}`) — 기존 fallback 분기 그대로 유지(P3 패턴), refs 없음.
- segments 없는 옛 노트(transcript_segments NULL): read view 좌측에서 트랜스크립트 패널 자리에 "트랜스크립트 없음" 메시지(또는 "타임라인 백필" 버튼 reuse — follow-up).

---

## 에러 처리
- LLM이 refs 누락 → paragraph만 노출, 첨자 안 보임 (graceful degrade).
- 비-YouTube 노트 read view 접근 → 메인으로 redirect (404 대신 친화적).
- segments 없는 노트 read view → 좌측 트랜스크립트 패널 자리에 안내 메시지, 영상은 정상.
- `_build_refs`: 잘못된 t/snippet skip — `_build_paragraphs`/`_build_sections`와 동일 가드 패턴.

---

## 테스트

### 단위
- `tests/test_claude_provider.py::test_build_refs`: 정상/잘못된 t/non-dict skip.
- `tests/test_claude_provider.py::test_summarize_quick_returns_paragraphs_with_refs`: mock JSON에 refs 포함 → res.paragraphs[0].refs 검증.
- `tests/test_claude_provider.py::test_summarize_detailed_items_have_refs`: detailed mock에 item.refs 포함 → 검증.
- `tests/test_models.py::test_init_db_adds_transcript_segments_idempotent`.
- `tests/test_storage.py::test_save_note_with_segments`: segments round-trip.

### 통합
- `tests/test_routes_youtube.py::test_youtube_pipes_segments_to_save_note`: do_work에서 save_note의 segments kwarg에 extract 결과 전달.
- `tests/test_routes_items.py::test_read_view_renders_youtube_note`: `/items/1/read` GET → 200, video iframe + transcript ul + paragraph 본문.
- `tests/test_routes_items.py::test_read_view_redirects_non_youtube`: PDF 노트 → 302/`/`.
- `tests/test_routes_items.py::test_modal_shows_full_screen_link_for_youtube`: 모달에 `/items/1/read` 링크 포함.
- `tests/test_routes_items.py::test_modal_paragraph_refs_render_chips`: refs 있는 paragraph → `[1][2]` 마크업 포함.

---

## Non-goals
- 본문 inline `[N]` 마커 (문장 중간) — paragraph 끝 첨자만.
- 트랜스크립트 segment 자동 highlight (현재 영상 시각 추적) — follow-up.
- 트랜스크립트 검색.
- PDF/Text/Code에 각주 (각자 다른 데이터 모델 필요 — 별도 spec).
- 페이지 단위 export/print 최적화.
- read view에서 노트 편집.

---

## 검증 (E2E)
1. `python -m pytest -q` — 새 테스트 통과.
2. 서버 재시작 후 YouTube 영상(자막 있는 것) 분석.
3. 모달 열기 → paragraph 끝에 `[1][2][3]` 첨자 노출 → 클릭 시 영상 점프.
4. 모달 우상단 📖 클릭 → 새 탭 `/items/{id}/read` 열림.
5. read view 좌측: 영상 + 트랜스크립트 list. 우측: 본문 + refs 첨자.
6. refs 첨자 클릭 → 영상 시각 점프.
7. 트랜스크립트 segment 클릭 → 영상 시각 점프.
8. 옛 노트(quote+t만 있는) 모달 → `[1]` 첨자 1개로 정상 표시.
9. 비-YouTube 노트 `/items/{id}/read` 직접 접근 → `/`로 redirect.
