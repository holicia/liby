# 상세 요약 UI 개선 5종 설계

**작성일:** 2026-05-28
**브랜치:** `feature/lilys-detailed-summary` (Lilys 스타일 상세 요약에 이어서)

## 개요

상세 요약 기능에 대한 후속 UI/동작 개선 5종. 모두 같은 브랜치에서 진행한다.

1. 모달 H2 대섹션 접기/펼치기 + 문단 간격 확대
2. 타임라인 챕터 한국어화(네이티브 비한국어면 번역)
3. 노트 카드 제목/본문 클릭으로 모달 열기 + "전체 보기" 버튼 제거
4. 사이드바 드래그 리사이즈
5. Source 입력 영역(밴드)을 화면 60% 폭으로 축소

## 1. 모달 H2 접기/펼치기 + 문단 간격

**파일:** `templates/partials/note_detail_modal.html`

- 계층 본문의 각 H2 대섹션을 `<details open>` + `<summary>`로 감싼다(기본 펼침, JS 불필요·접근성·HTMX 재주입 안전).
  - `id="sec-{{ sec_idx }}"`는 `<details>`에 둬 목차 앵커 유지.
  - `<summary>`에 H2 제목 + 회전 셰브론(`details[open]`일 때 회전). `summary`는 `cursor-pointer list-none`(기본 마커 제거).
  - H2 안의 `⏱` seek 버튼 `onclick`에 `event.stopPropagation()` 추가 → 펼침 토글과 충돌 방지.
  - H3 소섹션은 접기 대상 아님(대섹션만).
- **문단 간격(줄간격 ~2배):** 본문 블록 사이 간격 확대 — 대섹션 컨테이너 `space-y-6`, 소섹션 항목 리스트 `space-y-3`(기존 1.5), 본문 `leading-relaxed` 유지. 한 항목 내부 불릿(`space-y-1`)은 가독성 위해 촘촘히 둔다. 정확한 값은 브라우저 확인 후 미세 조정.

## 2. 타임라인 챕터 한국어화

**파일:** `services/chapters.py`, `services/ai/base.py`, `services/ai/claude.py`, `services/ai/openai_provider.py`

- `resolve_chapters(native_chapters, segments, ai)` 분기 변경:
  - 네이티브 챕터 있음 → `_labels_are_korean(native_chapters)`면 그대로 반환(비용 0); 아니면 `await ai.translate_chapters(native_chapters)`로 라벨만 한국어 번역(t 시점 보존).
  - 네이티브 없음 → 기존대로 `segments` 있으면 `ai.generate_chapters`, 없으면 `[]`.
- `_labels_are_korean(chapters) -> bool` (chapters.py): 라벨들을 합쳐 한글 음절(U+AC00–U+D7A3)이 하나라도 있으면 True. 영어 전용 라벨은 False → 번역.
- `translate_chapters(chapters) -> (list[dict], float, str)`:
  - `AIProvider`(base) 기본 구현: `return chapters, 0.0, ""` (FallbackProvider 등은 원본 유지).
  - claude/openai: 라벨 목록을 한국어로 번역하는 작은 LLM 호출. 입력 JSON `{"chapters":[{t,label}]}`, 출력 동일 형식. `_build_chapters`로 파싱(t 보존, 시간 오름차순). 비용은 호출 시에만 기록.
  - 프롬프트 상수 `TRANSLATE_CHAPTERS_PROMPT`(claude.py에 정의, openai import). "각 label을 자연스러운 한국어로 번역, t는 그대로."
- 적용: 신규 youtube 분석·상세정리 업그레이드·"타임라인 생성" 백필 모두 `resolve_chapters` 경유 → 자동 반영. 기존 영어 챕터 노트는 "타임라인 생성"/재분석으로 갱신.

## 3. 노트 카드 클릭으로 열기 + "전체 보기" 제거

**파일:** `templates/partials/note_card.html`

- 카드 내용 영역(제목 `div` + 요약 `<p>`를 감싸는 좌측 `flex-1` 블록)에 `hx-get="/api/items/{{ note.id }}/detail" hx-target="#note-modal" hx-swap="innerHTML"` 부여 → 클릭 시 상세 모달 오픈. 이미 `cursor-pointer`.
- 우측 컨트롤 열(프로젝트 셀렉트, ".md 열기", "상세 정리")은 별도 flex 컬럼이므로 클릭 전파 영향 없음(그대로 유지).
- **"전체 보기" 버튼 제거**(제목/본문 클릭이 대체).

## 4. 사이드바 드래그 리사이즈

**파일:** `templates/base.html`

- `<aside>`의 고정 `w-52` 클래스를 제거하고 인라인 `style="width:..."`로 제어(기본 208px).
- aside 우측 경계에 드래그 핸들 `<div class="w-1 cursor-col-resize hover:bg-[#1F6F4A]/30 ...">` 추가(레이아웃 flex row 안, aside와 main 사이).
- base.html `<script>`에 리사이즈 로직:
  - `mousedown`(핸들) → 드래그 시작, `mousemove`로 `aside.style.width = clamp(x, 160, 480)px`, `mouseup`에 `localStorage.setItem('sidebarWidth', w)` + 리스너 해제.
  - 로드 시 `localStorage`의 저장값 적용(없으면 208px).
  - 드래그 중 텍스트 선택 방지(`user-select:none` 토글).
- 범위: **160–480px**.

## 5. Source 입력 영역 60% 폭

**파일:** `templates/base.html`

- `#input-panel`을 화면 60% 폭으로 중앙 정렬: 컨테이너에 `w-[60%] mx-auto` 적용(밴드·divider 포함 60%). 패딩은 유지.
  - 현재 `class="bg-[#EAF4EE] border-b ... px-5 py-3"` → 폭 제한 + 중앙 정렬 추가. border-b가 60%만 그어지는 게 어색하면 바깥 래퍼는 전폭(배경/divider), 안쪽 60% 중앙 — 단, 사용자가 "밴드도 60%로"를 명시했으므로 **#input-panel 자체를 60% 중앙**으로 한다.

## 테스트

- **단위(#2):** `_labels_are_korean`(한글/영문/혼합), `resolve_chapters`가 비한국어 네이티브면 `translate_chapters` 호출·한국어면 그대로·네이티브 없으면 `generate_chapters`, `translate_chapters` mock 파싱.
- **브라우저(#1,#3,#4,#5):** 모달 H2 접기/펼치기·문단 간격·⏱ 클릭이 토글 안 함; 카드 제목 클릭 모달 오픈·전체보기 버튼 없음·컨트롤 클릭은 모달 안 열림; 사이드바 드래그 리사이즈+새로고침 후 복원; 입력 밴드 60% 중앙.

## 비목표

- 본문 섹션 헤딩 번역(이미 한국어), H3 접기, 기존 노트 챕터 일괄 백필 자동화, 모바일 반응형 정교화.
