# UX 폴리시 묶음 (2026-05-31) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 노트 삭제 기능, PDF 파일 선택 클릭 영역 픽스, 사이드바 헤더 텍스트 변경, 다크/라이트 토글 아이콘화 — 4건의 작은 UX 개선을 한 사이클로 처리.

**Architecture:** 1번(노트 삭제)만 새 HTTP path(`DELETE /api/items/{id}`) + storage 헬퍼 + 휴지통 버튼 2곳. 나머지 3건은 단일 템플릿/JS 변경. HTMX의 `hx-delete` + `hx-confirm` + `outerHTML` swap으로 카드 element를 빈 응답으로 교체해 UI에서 제거.

**Tech Stack:** FastAPI + HTMX(1.9.12) + Jinja2 + Tailwind, SQLite(aiosqlite), pytest + pytest-asyncio + httpx AsyncClient/ASGITransport. 브랜치: `feature/ux-polish-2026-05-31`.

---

## File Structure

**Modify:**
- `services/storage.py` — `delete_note` 추가
- `routers/items.py` — `DELETE /api/items/{id}` 핸들러 추가
- `templates/partials/note_card.html` — 루트 `<div>`에 id, 우측 버튼 컬럼에 휴지통
- `templates/partials/note_detail_modal.html` — 우상단 ✕ 옆에 휴지통
- `templates/partials/input_pdf.html` — `<input type=file>`을 `<label>`로 감싸기
- `templates/partials/api_cost.html` — 헤더 텍스트 1줄
- `templates/base.html` — 토글 버튼 + `toggleTheme()` JS

**Test:**
- `tests/test_storage.py` — `delete_note` 2개
- `tests/test_routes_items.py` — `DELETE /api/items/{id}` 2개

기존 108 테스트 → 112로 증가 예상.

---

## Task 1: `delete_note` 헬퍼 (storage 계층)

**Files:**
- Modify: `services/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 실패 테스트 2개 추가**

`tests/test_storage.py` 맨 아래에 append:
```python
@pytest.mark.asyncio
async def test_delete_note_removes_row_and_returns_md_path(db, tmp_path):
    from services.storage import delete_note, get_note
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    saved = await get_note(db, nid)
    saved_path = saved["md_file_path"]
    returned = await delete_note(db, nid)
    assert returned == saved_path
    assert await get_note(db, nid) is None


@pytest.mark.asyncio
async def test_delete_note_unknown_id_returns_none(db):
    from services.storage import delete_note
    assert await delete_note(db, 999999) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_storage.py -k delete_note -v`
Expected: FAIL with `ImportError: cannot import name 'delete_note'`.

- [ ] **Step 3: `delete_note` 구현**

`services/storage.py`의 `save_note` 함수 정의 바로 뒤(현재 line 145 직후)에 append:
```python
async def delete_note(db_path: str, note_id: int) -> str | None:
    """노트 row를 삭제하고 저장돼 있던 md_file_path를 반환(없으면 None).
    호출자가 반환값을 받아 파일을 unlink한다(파일/DB 트랜잭션 분리)."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT md_file_path FROM items WHERE id=?", (note_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("DELETE FROM items WHERE id=?", (note_id,))
        await db.commit()
        return row[0]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_storage.py -k delete_note -v`
Expected: 2 passed.

- [ ] **Step 5: 전체 회귀 확인 + 커밋**

Run: `python -m pytest -q`
Expected: 110 passed (기존 108 + 2 신규).

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: add delete_note storage helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `DELETE /api/items/{id}` 라우트 + 멱등성

**Files:**
- Modify: `routers/items.py`
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 2개 추가**

`tests/test_routes_items.py` 맨 아래에 append:
```python
@pytest.mark.asyncio
async def test_delete_item_removes_db_row_and_file(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("body", encoding="utf-8")
    async def fake_delete_note(db, nid):
        assert nid == 1
        return str(md)
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/1")
    assert resp.status_code == 200
    assert resp.text == ""
    assert not md.exists()


@pytest.mark.asyncio
async def test_delete_item_is_idempotent_when_row_missing(tmp_path):
    async def fake_delete_note(db, nid): return None  # 이미 지워졌거나 미존재
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/999")
    assert resp.status_code == 200
    assert resp.text == ""


@pytest.mark.asyncio
async def test_delete_item_swallows_missing_file(tmp_path):
    missing = tmp_path / "gone.md"  # 파일 존재 안 함
    async def fake_delete_note(db, nid): return str(missing)
    with patch("routers.items.delete_note", new=fake_delete_note):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/items/1")
    assert resp.status_code == 200
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_items.py -k delete_item -v`
Expected: FAILs (라우트 없어서 404 또는 405).

- [ ] **Step 3a: import 갱신** — `routers/items.py` line 7-11

```python
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes,
    list_projects, set_note_project, set_timeline,
    delete_note,
)
```
(`delete_note`를 마지막에 추가)

- [ ] **Step 3b: 라우트 핸들러 추가**

`routers/items.py`의 `get_item_detail` 함수(line 52-61) 직후에 append:
```python
@router.delete("/{note_id}")
async def delete_item(note_id: int):
    from fastapi.responses import HTMLResponse
    from pathlib import Path
    md_path = await delete_note(config.DB_PATH, note_id)
    if md_path:
        try:
            Path(md_path).unlink()
        except FileNotFoundError:
            pass
    return HTMLResponse(content="", status_code=200)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -k delete_item -v`
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀 확인 + 커밋**

Run: `python -m pytest -q`
Expected: 113 passed (110 + 3 신규).

```bash
git add routers/items.py tests/test_routes_items.py
git commit -m "feat: DELETE /api/items/{id} with idempotent file unlink

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: 카드 우하단 휴지통 버튼

**Files:**
- Modify: `templates/partials/note_card.html`

- [ ] **Step 1: 루트 `<div>`에 id 부여** — `templates/partials/note_card.html:2`

기존:
```html
<div class="note-card bg-[#F3F5F4] border border-[#E2E8E4] rounded-xl p-4 flex gap-3 items-start hover:border-[#A8CBB2] hover:shadow-sm transition-all cursor-pointer dark:bg-gray-800 dark:border-gray-700">
```
신규(id 추가):
```html
<div id="note-card-{{ note.id }}" class="note-card bg-[#F3F5F4] border border-[#E2E8E4] rounded-xl p-4 flex gap-3 items-start hover:border-[#A8CBB2] hover:shadow-sm transition-all cursor-pointer dark:bg-gray-800 dark:border-gray-700">
```

- [ ] **Step 2: 우측 버튼 컬럼에 휴지통 추가** — `templates/partials/note_card.html:51-53` 직후

기존(`.md 열기` 버튼 직후):
```html
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors dark:bg-gray-700"
            hx-post="/api/items/{{ note.id }}/open-md"
            hx-swap="none">.md 열기</button>
  </div>
```
신규(휴지통 버튼 추가):
```html
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors dark:bg-gray-700"
            hx-post="/api/items/{{ note.id }}/open-md"
            hx-swap="none">.md 열기</button>
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-400 hover:bg-red-50 hover:text-red-500 hover:border-red-200 transition-colors dark:bg-gray-700"
            hx-delete="/api/items/{{ note.id }}"
            hx-confirm="이 노트를 삭제하시겠어요? .md 파일도 함께 사라집니다."
            hx-target="#note-card-{{ note.id }}"
            hx-swap="outerHTML">🗑</button>
  </div>
```

- [ ] **Step 3: 라우트 응답에 휴지통이 포함되는지 회귀 테스트 추가** — `tests/test_routes_items.py`에 append

```python
@pytest.mark.asyncio
async def test_card_renders_delete_button():
    """카드에 hx-delete 휴지통 버튼이 렌더돼야 한다."""
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items")
    assert resp.status_code == 200
    assert 'hx-delete="/api/items/1"' in resp.text
    assert 'id="note-card-1"' in resp.text
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -k card_renders_delete -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add templates/partials/note_card.html tests/test_routes_items.py
git commit -m "feat: card trash button with hx-delete

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 모달 우상단 휴지통 버튼

**Files:**
- Modify: `templates/partials/note_detail_modal.html`

- [ ] **Step 1: ✕ 옆에 휴지통 추가** — `templates/partials/note_detail_modal.html:10-11`

기존(닫기 버튼만 있음):
```html
    <!-- 닫기 -->
    <button onclick="closeNoteModal()"
            class="absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 transition-colors text-sm font-bold">✕</button>
```
신규(휴지통 + 닫기):
```html
    <!-- 삭제 -->
    <button hx-delete="/api/items/{{ note.id }}"
            hx-confirm="이 노트를 삭제하시겠어요? .md 파일도 함께 사라집니다."
            hx-target="#note-card-{{ note.id }}"
            hx-swap="outerHTML"
            hx-on::after-request="closeNoteModal()"
            class="absolute top-4 right-14 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/40 transition-colors text-sm">🗑</button>
    <!-- 닫기 -->
    <button onclick="closeNoteModal()"
            class="absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 transition-colors text-sm font-bold">✕</button>
```

- [ ] **Step 2: 라우트 응답에 휴지통이 포함되는지 회귀 테스트** — `tests/test_routes_items.py`에 append

```python
@pytest.mark.asyncio
async def test_modal_renders_delete_button():
    """모달 우상단에 hx-delete 휴지통이 렌더돼야 한다."""
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert 'hx-delete="/api/items/1"' in resp.text
    assert 'closeNoteModal()' in resp.text
```

- [ ] **Step 3: 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -k modal_renders_delete -v`
Expected: PASS.

- [ ] **Step 4: 전체 회귀 확인 + 커밋**

Run: `python -m pytest -q`
Expected: 115 passed (113 + 2 신규 from Task 3, 4).

```bash
git add templates/partials/note_detail_modal.html tests/test_routes_items.py
git commit -m "feat: modal trash button with HTMX delete + auto-close

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: PDF 파일 입력 클릭 영역 픽스

**Files:**
- Modify: `templates/partials/input_pdf.html`

- [ ] **Step 1: input을 label로 감싸 클릭 영역 확장**

전체 교체 — `templates/partials/input_pdf.html` 라인 1-16:
```html
<form hx-post="/api/pdf" hx-target="#queue-panel" hx-swap="beforeend" hx-encoding="multipart/form-data" hx-include="#current-project" class="flex gap-2 items-center">
  <label class="flex-1 cursor-pointer flex items-center gap-2 bg-white border border-[#E2E8E4] rounded-lg px-3 py-2 text-xs text-gray-500 dark:bg-gray-800 hover:border-[#1F6F4A]">
    <span class="font-medium">📎 파일 선택</span>
    <span id="pdf-filename" class="text-gray-400 truncate">선택된 파일 없음</span>
    <input name="file" type="file" accept=".pdf" required class="hidden"
           onchange="document.getElementById('pdf-filename').textContent=this.files[0]?.name||'선택된 파일 없음'">
  </label>
  <select name="provider" class="bg-white border border-[#E2E8E4] rounded-lg px-3 py-2.5 text-xs text-gray-500 dark:bg-gray-800">
    <option value="claude">Claude</option>
    <option value="gpt">GPT</option>
  </select>
  <select name="mode" class="bg-white border border-[#E2E8E4] rounded-lg px-3 py-2.5 text-xs text-gray-500 dark:bg-gray-800">
    <option value="quick">빠른 정리</option>
    <option value="detailed">상세 정리</option>
  </select>
  <button type="submit" class="bg-[#1F6F4A] text-white rounded-lg px-5 py-2.5 text-xs font-semibold hover:opacity-90 transition-opacity whitespace-nowrap">
    분석하기
  </button>
</form>
```

- [ ] **Step 2: partial 라우트 응답 검증 테스트 추가** — 새 파일 `tests/test_routes_partials.py` 생성

```python
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_pdf_input_partial_uses_label_wrapped_input():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/partials/input/pdf")
    assert resp.status_code == 200
    # input은 hidden, label이 전체 클릭 영역
    assert '<label' in resp.text
    assert 'class="hidden"' in resp.text
    assert 'pdf-filename' in resp.text
```

- [ ] **Step 3: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -v`
Expected: 1 passed.

- [ ] **Step 4: 커밋**

```bash
git add templates/partials/input_pdf.html tests/test_routes_partials.py
git commit -m "fix: wrap PDF input in label so click area covers full row

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: 사이드바 헤더 텍스트 변경

**Files:**
- Modify: `templates/partials/api_cost.html`

- [ ] **Step 1: 텍스트 1줄 교체** — `templates/partials/api_cost.html:3`

기존:
```html
    <span class="text-[10px] font-bold uppercase tracking-widest text-gray-400">이번 달 API</span>
```
신규:
```html
    <span class="text-[10px] font-bold uppercase tracking-widest text-gray-400">API 사용 현황</span>
```

- [ ] **Step 2: 라우트 응답 검증 테스트 추가** — `tests/test_routes_partials.py`에 append

```python
@pytest.mark.asyncio
async def test_api_cost_partial_uses_new_header_text():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/settings/cost")
    assert resp.status_code == 200
    assert "API 사용 현황" in resp.text
    assert "이번 달 API" not in resp.text
```

- [ ] **Step 3: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -k api_cost -v`
Expected: PASS.

- [ ] **Step 4: 커밋**

```bash
git add templates/partials/api_cost.html tests/test_routes_partials.py
git commit -m "feat: sidebar header text '이번 달 API' -> 'API 사용 현황'

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: 다크/라이트 토글 아이콘화

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: 토글 버튼 텍스트 → 아이콘 (이모지)** — `templates/base.html:35`

기존:
```html
    <button onclick="toggleTheme()" class="text-xs px-3 py-1 border border-[#E2E8E4] rounded-md text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors" id="theme-btn">다크 모드</button>
```
신규(텍스트 → 이모지, 사이즈 살짝 조정):
```html
    <button onclick="toggleTheme()" class="text-base px-2 py-1 border border-[#E2E8E4] rounded-md text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors" id="theme-btn" aria-label="테마 전환">🌙</button>
```

- [ ] **Step 2: toggleTheme JS 갱신** — `templates/base.html:133-140`

기존:
```javascript
function toggleTheme() {
  const html = document.documentElement;
  const btn = document.getElementById("theme-btn");
  const isDark = !html.classList.contains("dark");
  html.classList.toggle("dark", isDark);
  html.setAttribute("data-theme", isDark ? "dark" : "light");
  btn.textContent = isDark ? "라이트 모드" : "다크 모드";
}
```
신규(텍스트 → 아이콘):
```javascript
function toggleTheme() {
  const html = document.documentElement;
  const btn = document.getElementById("theme-btn");
  const isDark = !html.classList.contains("dark");
  html.classList.toggle("dark", isDark);
  html.setAttribute("data-theme", isDark ? "dark" : "light");
  btn.textContent = isDark ? "☀️" : "🌙";
}
```

- [ ] **Step 3: 라우트 응답 검증 테스트 추가** — `tests/test_routes_partials.py`에 append

```python
@pytest.mark.asyncio
async def test_index_theme_toggle_uses_icon():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    # 토글 버튼 자체 + 초기 아이콘 (라이트 모드 시작 → 다음으로 갈 다크의 아이콘 🌙)
    assert 'id="theme-btn"' in resp.text
    assert '🌙' in resp.text
    assert '다크 모드' not in resp.text
    assert '라이트 모드' not in resp.text
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `python -m pytest tests/test_routes_partials.py -v`
Expected: 3 passed (Tasks 5, 6, 7).

Run: `python -m pytest -q`
Expected: 118 passed (115 + 3 신규 from Tasks 5, 6, 7).

- [ ] **Step 5: 커밋**

```bash
git add templates/base.html tests/test_routes_partials.py
git commit -m "feat: theme toggle icon (☀️/🌙) replaces text label

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: 브라우저 E2E 검증 (수동)

**Files:** 없음 (전 작업 통합 검증)

서버를 띄우고 시나리오 5개를 확인. 모두 PASS면 plan 종료.

- [ ] **Step 1: 서버 재시작**

```bash
# 기존 uvicorn 종료 후
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: 노트 1개 생성** (검증용 시드)

브라우저 `http://localhost:8000` → 텍스트 탭 → 짧은 문장 입력 → 빠른 정리. 분석 완료까지 대기.

- [ ] **Step 3: 카드 휴지통 검증**

- 새 노트 카드 우하단에 🗑 보임.
- 🗑 클릭 → 브라우저 confirm 다이얼로그 뜸.
- 확인 → 카드가 즉시 사라짐.
- DB 확인: `python -c "import sqlite3; print(sqlite3.connect('liby.db').execute('SELECT id FROM items ORDER BY id DESC LIMIT 1').fetchone())"` — 방금 노트 id 안 보임.
- vault 확인: `ls vault/text/` — 방금 .md 안 보임.

- [ ] **Step 4: 모달 휴지통 검증**

- 다시 노트 1개 생성. 카드 본문 영역(우측 버튼 컬럼 아닌 곳) 클릭 → 모달 열림.
- 모달 우상단 ✕ 왼쪽에 🗑 보임.
- 🗑 클릭 → confirm → 모달 닫힘 + 카드 사라짐. DB·vault에서도 사라짐.

- [ ] **Step 5: PDF 파일 입력 검증**

- PDF 탭 클릭.
- 입력 영역 어느 곳을 눌러도(좌측 "📎 파일 선택" 라벨이든 우측 "선택된 파일 없음" 부분이든) OS 파일 다이얼로그가 뜸.
- 파일 선택 → "선택된 파일 없음" → 선택한 파일명으로 즉시 바뀜.

- [ ] **Step 6: 사이드바 헤더 검증**

- 사이드바 하단의 헤더가 `API 사용 현황`으로 보임. `이번 달 API` 흔적 없음.

- [ ] **Step 7: 토글 아이콘 검증**

- 우측 상단 토글 버튼이 🌙 이모지 한 글자(텍스트 라벨 없음).
- 클릭 → 다크 모드 활성화 + 버튼이 ☀️로 바뀜.
- 다시 클릭 → 라이트 모드 + 🌙로 복귀.

모두 PASS면 Plan 완료.
