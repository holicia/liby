# UX 폴리시 묶음 (2026-05-31)

작은 UX·품질 개선 4건을 한 사이클로 처리. Discord 연동(5번)은 별도 spec/plan으로 분리.

**대상 분량:** S–M (구현 사이클 1회, 단일 plan)
**테스트 카운트 변동 예상:** +3 (delete_note 라운드트립 / DELETE 라우트 / 멱등성)

---

## 1. 노트 삭제 기능

### 동기
지금까지는 테스트로 만든 노트를 정리할 때마다 `sqlite3` + `pathlib.Path.unlink`를 수동 호출했다. 일반 사용 흐름에서도 노트를 지울 수 없다.

### 사용자 동선
- **카드**: 우하단 `.md 열기` 버튼 옆에 작은 휴지통 버튼. 클릭 → `window.confirm("이 노트를 삭제하시겠어요? .md 파일도 함께 사라집니다.")` → 카드 사라짐.
- **모달**: 우상단 ✕ 옆 같은 휴지통. 클릭 → 같은 confirm → 모달 닫힘 + 카드 사라짐.
- 확인 다이얼로그는 HTMX의 `hx-confirm`(브라우저 `confirm()` 래퍼)로 처리. JS 추가 없음.

### 백엔드
- `services/storage.py::delete_note(db_path, note_id) -> str | None`:
  - `SELECT md_file_path FROM items WHERE id=?` → 경로 또는 `None`.
  - `DELETE FROM items WHERE id=?`.
  - 경로 반환 (없으면 `None`).
- `routers/items.py::delete_item`:
  - `@router.delete("/{note_id}")` → `delete_note` 호출, 반환된 경로가 있으면 `try: Path(path).unlink() except FileNotFoundError: pass`.
  - 응답: `HTMLResponse(content="", status_code=200)` (HTMX outerHTML swap이 카드 element를 빈 응답으로 교체 → 사라짐).
- **멱등성**: 이미 지워진 id로 다시 호출돼도 200 + 빈 응답 (DELETE 자체는 영향 없음, unlink는 FileNotFoundError 흡수).

### 템플릿 변경
- `templates/partials/note_card.html`:
  - 루트 `<div>`에 `id="note-card-{{ note.id }}"` 추가 (기존 `class="note-card"` 유지).
  - 우하단 영역에 휴지통 버튼 추가:
    ```html
    <button hx-delete="/api/items/{{ note.id }}"
            hx-confirm="이 노트를 삭제하시겠어요? .md 파일도 함께 사라집니다."
            hx-target="#note-card-{{ note.id }}"
            hx-swap="outerHTML"
            class="text-gray-400 hover:text-red-500 text-sm">🗑</button>
    ```
- `templates/partials/note_detail_modal.html`: 우상단 `✕` 옆에 같은 버튼. `hx-target="#note-card-{{ note.id }}"`(카드 element를 빈 응답으로 교체)와 `hx-on::after-request="closeNoteModal()"`(모달도 닫음) 추가. `closeNoteModal()`은 `base.html:287`에 이미 정의돼 있어 재사용.

### 테스트
- `tests/test_storage.py::test_delete_note_removes_row_and_returns_md_path`: 노트 저장 → `delete_note` → row 사라짐 + 반환 경로 == 저장 시 경로.
- `tests/test_storage.py::test_delete_note_unknown_id_returns_none`.
- `tests/test_routes_items.py::test_delete_item_removes_db_row_and_file`: 임시 파일 생성 → `DELETE /api/items/{id}` → 200 빈 응답 + DB row 사라짐 + 파일 사라짐.
- `tests/test_routes_items.py::test_delete_item_is_idempotent`: 한 번 더 호출 → 200 (404 아님).

---

## 2. PDF "파일 선택" 무동작

### 원인 가설
`<input type="file">`이 flex container 안 좁은 영역에 위치하면서 사용자가 input 영역을 클릭해도 native 'Choose File' 버튼 hit-area가 좁아 동작하지 않는 것처럼 느낌. (Playwright 자동화에서는 file chooser가 정상 호출되는 걸로 확인 — 환경 차이가 아니라 hit-area UX 문제.)

### 해결
`<input>`을 `<label>`로 감싸 라벨 전체를 클릭 영역으로. 선택 파일명은 inline JS로 즉시 표시.

`templates/partials/input_pdf.html`:
```html
<label class="flex-1 cursor-pointer flex items-center gap-2 bg-white border border-[#E2E8E4] rounded-lg px-3 py-2 text-xs text-gray-500 dark:bg-gray-800 hover:border-[#1F6F4A]">
  <span class="font-medium">📎 파일 선택</span>
  <span id="pdf-filename" class="text-gray-400 truncate">선택된 파일 없음</span>
  <input name="file" type="file" accept=".pdf" required class="hidden"
         onchange="document.getElementById('pdf-filename').textContent=this.files[0]?.name||'선택된 파일 없음'">
</label>
```
나머지 form 요소(provider/mode/submit)는 그대로.

### 테스트
- 단위 테스트 없음 (UI 동작은 자동화로 검증 어렵고 변경이 작음). 브라우저 검증으로 마무리.

---

## 3. 사이드바 헤더 텍스트 변경

`templates/partials/api_cost.html` 안의 `이번 달 API` 한 줄을 `API 사용 현황`으로 교체.

### 테스트
없음.

---

## 4. 다크/라이트 토글 아이콘화

### 변경
`templates/base.html` 우측 네비 토글 버튼:
- 현재: `<button ...>다크 모드</button>`
- 신규: `<button id="theme-toggle" aria-label="테마 전환"><span id="theme-icon">🌙</span></button>`

토글 JS 함수에서 현재 dark면 `☀️`, light면 `🌙`로 텍스트 바꿈. 토글 시 swap 한 줄 추가.

### 테스트
없음(시각적 변경).

---

## 데이터 흐름 요약
1번만 새 HTTP path. 나머지 3건은 템플릿 변경.

```
[카드 클릭] → confirm() → DELETE /api/items/{id}
                              ↓
                       delete_note(...) → md path
                              ↓
                     try unlink (FileNotFoundError 무시)
                              ↓
                       빈 200 → outerHTML swap → 카드 사라짐
```

## 에러 처리
- **DB row 없음**: `delete_note`가 `None` 반환 → 라우터는 unlink 스킵 + 200 빈 응답(멱등).
- **md 파일 없음**: `unlink`의 `FileNotFoundError` 흡수(같은 멱등 보장).
- **DB·파일 권한 오류**: 발생하면 500. 사용자에게는 카드가 그대로 남는 것으로 노출. 별도 친화 메시지 처리는 비목표.

## Non-goals
- soft delete / trash 페이지 / undo (YAGNI — `window.confirm`이 안전망).
- 다중 선택 삭제.
- 카드의 "..." 드롭다운 메뉴 (휴지통 직접 노출만).
- Discord 봇 연동 (별도 spec).

## 테스트 계획 요지
- pytest 신규 4개 (delete 관련). 기존 108개 + 4 = 112개로 늘어야.
- 브라우저 E2E: (a) 노트 생성 → 카드 휴지통 클릭 → confirm → 카드 사라짐 + vault .md도 사라짐 확인, (b) 노트 다시 생성 → 모달 휴지통 → 모달 닫힘 + 카드 사라짐, (c) PDF 탭에서 라벨 전체 클릭 시 file dialog 뜸, (d) 사이드바 헤더 문구 + 토글 아이콘.
