# liby 모바일 UI 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 폰 메인 앱을 열람 중심으로 정리 — 노트 카드 세로화(컨트롤은 모달로), 상단 입력영역 접기, 추천 1열. 데스크톱(`md+`)은 현행 유지.

**Architecture:** 순수 Tailwind 반응형(`hidden md:flex`/`hidden md:block`/`grid-cols-1 md:grid-cols-2`) + 소량 바닐라 JS 토글. 카드 컨트롤을 모바일에서 숨기는 대신 상세 모달에 프로젝트 지정·상세정리 액션을 추가해 관리 경로를 보존(detail 라우트가 `projects`를 넘기도록 보강).

**Tech Stack:** FastAPI + Jinja2 + HTMX + Tailwind(CDN). 테스트: pytest + httpx ASGITransport.

---

## 참고: 테스트 픽스처 패턴 (이미 존재)

`tests/test_routes_items.py` 상단:
```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
import config
from main import app
MOCK_NOTE = { "id": 1, "type": "youtube", "title": "테스트", "summary": "요약",
  "tags": '["AI"]', "topic": "AI/ML", "summary_mode": "quick",
  "key_points": '["핵심1"]', "ai_provider": "claude",
  "api_cost_usd": 0.003, "created_at": "2026-05-23",
  "source_url": "https://youtube.com/watch?v=abc" }
```
- 카드 목록: `GET /api/items` + `patch("routers.items.list_notes", return_value=[MOCK_NOTE])` + `patch("routers.items.list_projects", return_value=[])`.
- 모달: `GET /api/items/1/detail` + `patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE)`.
- index/base: `tests/test_routes_partials.py`에서 `GET /`.

이 머신은 pytest가 느림(~35초, 백그라운드화). 타깃 실행: `python -m pytest <path> -q 2>&1 | tail -5`.

---

## Task 1: note_card.html — 모바일에서 컨트롤 컬럼 숨김

**Files:**
- Modify: `templates/partials/note_card.html`
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_items.py 끝)

```python
@pytest.mark.asyncio
async def test_card_hides_controls_on_mobile():
    """노트 카드 우측 컨트롤 컬럼이 모바일에서 숨겨진다(hidden md:flex)."""
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items")
    assert resp.status_code == 200
    assert "hidden md:flex flex-col gap-1" in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_items.py::test_card_hides_controls_on_mobile -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3: 구현** — `templates/partials/note_card.html`

old:
```
  <div class="flex flex-col gap-1 flex-shrink-0">
```
new:
```
  <div class="hidden md:flex flex-col gap-1 flex-shrink-0">
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -q 2>&1 | tail -5`
Expected: PASS (기존 + 신규)

- [ ] **Step 5: 커밋**

```bash
git add templates/partials/note_card.html tests/test_routes_items.py
git commit -m "feat(mobile): 노트 카드 컨트롤 컬럼 모바일 숨김"
```

---

## Task 2: 상세 모달에 프로젝트 지정·상세정리 액션 추가

카드 컨트롤이 모바일에서 사라지므로 모달에서 관리. detail 라우트가 `projects`를 넘기도록 보강 + 모달에 액션 행 추가.

**Files:**
- Modify: `routers/items.py` (detail 라우트, lines 61-70)
- Modify: `templates/partials/note_detail_modal.html` (헤더 아래 액션 행)
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_items.py 끝)

```python
@pytest.mark.asyncio
async def test_modal_has_mobile_management_actions():
    """모달에 프로젝트 지정 셀렉트 + 상세정리(quick) 버튼이 노출된다."""
    with patch("routers.items.get_note", new_callable=AsyncMock, return_value=MOCK_NOTE), \
         patch("routers.items.list_projects", new_callable=AsyncMock, return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/1/detail")
    assert resp.status_code == 200
    assert 'hx-post="/api/items/1/project"' in resp.text
    assert 'hx-post="/api/items/1/upgrade"' in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_items.py::test_modal_has_mobile_management_actions -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3a: detail 라우트가 projects 전달** — `routers/items.py`

old:
```python
@router.get("/{note_id}/detail")
async def get_item_detail(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    video_id = None
    if note and note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": note, "video_id": video_id},
    )
```
new:
```python
@router.get("/{note_id}/detail")
async def get_item_detail(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    video_id = None
    if note and note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": note, "video_id": video_id, "projects": projects},
    )
```
(`list_projects`는 이미 import 되어 있음 — `routers/items.py:11`.)

- [ ] **Step 3b: 모달에 액션 행 삽입** — `templates/partials/note_detail_modal.html`

헤더 div 닫힘 직후, 영상 블록 앞에 삽입.

old:
```
    </div>

    <!-- 영상 임베드 + 챕터 -->
    {% if video_id %}
```
new:
```
    </div>

    <!-- 관리 액션 (프로젝트 지정 · 상세 정리) — 모바일 카드에서 컨트롤이 숨겨지므로 여기서 처리 -->
    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <select name="project_id"
              class="text-[11px] bg-white border border-[#E2E8E4] rounded px-2 py-1 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
              hx-post="/api/items/{{ note.id }}/project"
              hx-trigger="change"
              hx-target="#note-card-{{ note.id }}"
              hx-swap="outerHTML">
        <option value="" {% if not note.project_id %}selected{% endif %}>미분류</option>
        {% for p in projects or [] %}
        <option value="{{ p.id }}" {% if note.project_id == p.id %}selected{% endif %}>{{ p.name }}</option>
        {% endfor %}
      </select>
      {% if note.summary_mode == 'quick' %}
      <button class="text-[11px] bg-[#1F6F4A] text-white rounded px-3 py-1 font-semibold hover:opacity-90"
              hx-post="/api/items/{{ note.id }}/upgrade"
              hx-target="#queue-panel"
              hx-swap="beforeend">상세 정리</button>
      {% endif %}
    </div>

    <!-- 영상 임베드 + 챕터 -->
    {% if video_id %}
```

- [ ] **Step 4: 통과 확인 (items 파일 전체)**

Run: `python -m pytest tests/test_routes_items.py -q 2>&1 | tail -5`
Expected: PASS. 기존 모달 테스트들은 이제 detail 라우트가 실제 `list_projects(config.DB_PATH)`를 호출하게 됨(실 DB의 프로젝트 목록 반환). 셀렉트가 추가될 뿐 기존 단언 문자열은 그대로라 통과해야 한다. 만약 어떤 기존 모달 테스트가 깨지면 그 테스트에 `patch("routers.items.list_projects", new_callable=AsyncMock, return_value=[])`를 추가.

- [ ] **Step 5: 커밋**

```bash
git add routers/items.py templates/partials/note_detail_modal.html tests/test_routes_items.py
git commit -m "feat(mobile): 상세 모달에 프로젝트 지정·상세정리 액션 추가"
```

---

## Task 3: base.html — 상단 입력영역 접기 + 네비 탭 데스크톱 전용

**Files:**
- Modify: `templates/base.html`
- Test: `tests/test_routes_partials.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_partials.py 끝)

```python
@pytest.mark.asyncio
async def test_index_has_analysis_toggle_and_collapsible_input():
    """모바일: + 분석 토글 + 접히는 입력 래퍼 + 탭 데스크톱 전용."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'id="analysis-toggle"' in resp.text
    assert 'id="analysis-panel"' in resp.text
    assert "function toggleAnalysis" in resp.text
    assert "hidden md:block" in resp.text          # 입력 래퍼
    assert "hidden md:flex items-stretch" in resp.text  # 탭 컨테이너
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_index_has_analysis_toggle_and_collapsible_input -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3a: 입력 타입 탭 데스크톱 전용**

old:
```
  <div class="flex items-stretch overflow-x-auto">
    {% for tab in [("YouTube","youtube"),("PDF","pdf"),("Code","code"),("Text","text"),("Markdown","markdown")] %}
```
new:
```
  <div class="hidden md:flex items-stretch overflow-x-auto">
    {% for tab in [("YouTube","youtube"),("PDF","pdf"),("Code","code"),("Text","text"),("Markdown","markdown")] %}
```

- [ ] **Step 3b: 네비바에 + 분석 토글 버튼 추가**

old:
```
  <div class="ml-auto flex items-center">
    <button onclick="toggleTheme()" class="text-base px-2 py-1 border border-[#E2E8E4] rounded-md text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors" id="theme-btn" aria-label="테마 전환">🌙</button>
  </div>
```
new:
```
  <div class="ml-auto flex items-center gap-1">
    <button id="analysis-toggle" onclick="toggleAnalysis()" aria-label="분석 입력 열기"
            class="md:hidden text-xs px-2 py-1 border border-[#E2E8E4] rounded-md text-[#1F6F4A] dark:border-gray-700 dark:text-[#34A66A]">+ 분석</button>
    <button onclick="toggleTheme()" class="text-base px-2 py-1 border border-[#E2E8E4] rounded-md text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors" id="theme-btn" aria-label="테마 전환">🌙</button>
  </div>
```

- [ ] **Step 3c: 입력 패널 + 프로젝트바를 #analysis-panel로 감싸기 (시작)**

old:
```
    <!-- INPUT PANEL -->
    <div id="input-panel" class="bg-[#EAF4EE] border-b border-[#E2E8E4] px-5 py-3 dark:bg-[#14291E] dark:border-gray-700">
```
new:
```
    <!-- INPUT PANEL (모바일: + 분석 토글로 펼침) -->
    <div id="analysis-panel" class="hidden md:block">
    <div id="input-panel" class="bg-[#EAF4EE] border-b border-[#E2E8E4] px-5 py-3 dark:bg-[#14291E] dark:border-gray-700">
```

- [ ] **Step 3d: #analysis-panel 닫기 (프로젝트바 직후, QUEUE PANEL 앞)**

old:
```
    </div>
    <!-- QUEUE PANEL -->
```
new:
```
    </div>
    </div>
    <!-- QUEUE PANEL -->
```

- [ ] **Step 3e: toggleAnalysis JS 추가 (toggleTheme 앞)**

old:
```
function toggleTheme() {
  const html = document.documentElement;
  const btn = document.getElementById("theme-btn");
```
new:
```
function toggleAnalysis() {
  const p = document.getElementById('analysis-panel');
  if (!p) return;
  p.classList.toggle('hidden');
}
function toggleTheme() {
  const html = document.documentElement;
  const btn = document.getElementById("theme-btn");
```
(데스크톱은 `md:block`이 `hidden`을 무시하므로 toggleAnalysis는 데스크톱에서 무영향.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -q 2>&1 | tail -5`
Expected: PASS (기존 + 신규). 기존 `test_index_*` 단언(예: 탭 텍스트 "YouTube" 등)은 마크업이 숨겨질 뿐 텍스트는 남으므로 통과.

- [ ] **Step 5: 커밋**

```bash
git add templates/base.html tests/test_routes_partials.py
git commit -m "feat(mobile): 상단 입력영역 접기 + 네비 탭 데스크톱 전용"
```

---

## Task 4: index.html — 추천 노트 그리드 모바일 1열

**Files:**
- Modify: `templates/index.html`
- Test: `tests/test_routes_partials.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_partials.py 끝)

```python
@pytest.mark.asyncio
async def test_recommended_grid_single_col_mobile():
    """추천 노트 그리드가 모바일 1열·데스크톱 2열."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "grid-cols-1 md:grid-cols-2" in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_recommended_grid_single_col_mobile -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3: 구현** — `templates/index.html`

old:
```
       class="grid grid-cols-2 gap-2">
```
new:
```
       class="grid grid-cols-1 md:grid-cols-2 gap-2">
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -q 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add templates/index.html tests/test_routes_partials.py
git commit -m "feat(mobile): 추천 노트 그리드 모바일 1열"
```

---

## Task 5: 전체 회귀 + 모바일 육안 검증

**Files:** (검증 전용)

- [ ] **Step 1: 전체 스위트**

Run: `python -m pytest -q 2>&1 | tail -6`
Expected: 기존 합계 + 신규 4개 모두 통과, exit=0.

- [ ] **Step 2: Playwright 모바일 캡처 (서버 실행 중일 때)**

390px 폭으로 `/` 캡처 → 카드 제목 전체폭(짜부라짐 없음), 컨트롤 컬럼 비노출, 네비 스크롤바 없음, 입력영역 접힘, 추천 1열 확인. `+ 분석` 탭 → 입력 펼침. 카드 탭 → 모달에 프로젝트/상세정리.
(서버 미기동 시 controller가 별도 기동 후 캡처)

- [ ] **Step 3: (실패 시) systematic-debugging으로 격리 후 수정·재실행**

전부 통과 + 캡처 양호하면 완료.

---

## Self-Review 결과

- **Spec 커버리지:** A 카드 숨김(T1), B 모달 액션+detail projects(T2), C 입력 접기·탭 데스크톱전용·toggleAnalysis(T3), D 추천 1열(T4), 테스트(각 Step1 + T5), 비목표 준수(데스크톱 변경 없음·기능 추가 없이 재배치만) ✅
- **플레이스홀더:** 없음 — 모든 edit에 exact old/new, 모든 테스트에 실제 코드.
- **이름/일관성:** `#analysis-panel`/`#analysis-toggle`/`toggleAnalysis`/`hidden md:block`/`hidden md:flex`/`grid-cols-1 md:grid-cols-2` 전 Task 일치. 모달 액션은 기존 엔드포인트(`/project`,`/upgrade`) 재사용 — 신규 라우트 없음. detail 라우트 `projects` 전달이 모달 셀렉트의 전제(T2 3a에서 보장).
