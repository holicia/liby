# liby 모바일 입력 패널 + iOS Safari 입력 최적화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모바일에서 `+ 분석`으로 펼친 입력 폼이 가로폭에 맞게 세로 정렬되고, iOS Safari 입력 포커스 자동 확대를 막는다. 데스크톱(`md+`)은 현행 유지.

**Architecture:** 순수 Tailwind 반응형(`flex flex-col md:flex-row`) + base.html `<style>`에 모바일 폼 컨트롤 16px 미디어쿼리(iOS 줌 워크어라운드). 변경 2개 파일.

**Tech Stack:** FastAPI + Jinja2 + HTMX + Tailwind(CDN). 테스트: pytest + httpx ASGITransport (`tests/test_routes_partials.py`).

---

## 참고: 테스트 패턴 (이미 존재)

`tests/test_routes_partials.py` 상단 import: `pytest`, `AsyncClient`, `ASGITransport`, `app`.
- 입력 partial: `await c.get("/partials/input/youtube")` (기존 `test_pdf_input_partial_uses_label_wrapped_input`가 `/partials/input/pdf` 사용).
- base.html/index: `await c.get("/")`.

이 머신은 pytest가 느림(~35초, 백그라운드화). 타깃: `python -m pytest <path> -q 2>&1 | tail -5`.

---

## Task 1: input_youtube.html 폼 모바일 세로 스택

**Files:**
- Modify: `templates/partials/input_youtube.html`
- Test: `tests/test_routes_partials.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_partials.py 끝)

```python
@pytest.mark.asyncio
async def test_youtube_input_form_stacks_on_mobile():
    """+ 분석 입력 폼이 모바일 세로 스택·데스크톱 한 줄."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/partials/input/youtube")
    assert resp.status_code == 200
    assert "flex flex-col md:flex-row" in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_youtube_input_form_stacks_on_mobile -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3a: 폼 컨테이너 반응형** — `templates/partials/input_youtube.html`

old:
```
<form hx-post="/api/youtube" hx-target="#queue-panel" hx-swap="beforeend" hx-include="#current-project" class="flex gap-2 items-center">
```
new:
```
<form hx-post="/api/youtube" hx-target="#queue-panel" hx-swap="beforeend" hx-include="#current-project" class="flex flex-col md:flex-row gap-2 md:items-center">
```

- [ ] **Step 3b: URL 입력 flex-1을 데스크톱 전용으로**

old:
```
         class="flex-1 bg-white border border-[#E2E8E4] rounded-lg px-4 py-2.5 text-sm text-gray-700 outline-none focus:border-[#1F6F4A] dark:bg-gray-800 dark:text-gray-200">
```
new:
```
         class="md:flex-1 bg-white border border-[#E2E8E4] rounded-lg px-4 py-2.5 text-sm text-gray-700 outline-none focus:border-[#1F6F4A] dark:bg-gray-800 dark:text-gray-200">
```

> 모바일 `flex-col`에서 `flex-1`은 주축(세로)으로 늘어나 입력창이 세로로 길어진다. 데스크톱에서만 `flex-1`(가로 신장) 적용. 모바일은 기본 `align-items: stretch`로 각 컨트롤이 전체폭이 된다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -q 2>&1 | tail -5`
Expected: PASS (기존 + 신규). 기존 `test_index_input_forms_offer_cli_providers`(provider 옵션 존재) 등은 옵션 텍스트가 그대로라 통과.

- [ ] **Step 5: 커밋**

```bash
git add templates/partials/input_youtube.html tests/test_routes_partials.py
git commit -m "fix(mobile): YouTube 입력 폼 모바일 세로 스택"
```

---

## Task 2: base.html — iOS Safari 입력 자동 확대 방지

**Files:**
- Modify: `templates/base.html` (`<style>` 블록)
- Test: `tests/test_routes_partials.py`

- [ ] **Step 1: 실패 테스트 추가** (tests/test_routes_partials.py 끝)

```python
@pytest.mark.asyncio
async def test_index_prevents_ios_input_zoom():
    """모바일 폼 컨트롤 16px 규칙으로 iOS Safari 포커스 자동확대 방지."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "max-width: 767px" in resp.text
    assert "font-size: 16px" in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_index_prevents_ios_input_zoom -q 2>&1 | tail -5`
Expected: FAIL

- [ ] **Step 3: 구현** — `templates/base.html` `<style>` 블록에 미디어쿼리 추가

old:
```
  /* 모바일 주소창(동적 툴바) 대응: 100vh 대신 동적 뷰포트 높이로 상단 가림 방지 */
  .dvh-screen { height: 100vh; height: 100dvh; }
</style>
```
new:
```
  /* 모바일 주소창(동적 툴바) 대응: 100vh 대신 동적 뷰포트 높이로 상단 가림 방지 */
  .dvh-screen { height: 100vh; height: 100dvh; }
  /* iOS Safari: 16px 미만 폼 컨트롤 포커스 시 자동 확대 → 모바일에서 16px로 막음 */
  @media (max-width: 767px) {
    input, select, textarea { font-size: 16px !important; }
  }
</style>
```

> `!important`는 Tailwind의 `text-xs`/`text-sm` 유틸(클래스 우선순위)을 이겨 폼 컨트롤 글꼴을 16px로 강제하기 위해 필요(iOS zoom 표준 워크어라운드). 미디어쿼리 `<768px`라 데스크톱 무영향.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -q 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add templates/base.html tests/test_routes_partials.py
git commit -m "fix(mobile): iOS Safari 입력 포커스 자동 확대 방지(16px)"
```

---

## Task 3: 전체 회귀 + Playwright 모바일 검증

**Files:** (검증 전용)

- [ ] **Step 1: 전체 스위트**

Run: `python -m pytest -q 2>&1 | tail -6`
Expected: 기존 264 + 신규 2 = 266 passed, exit=0.

- [ ] **Step 2: Playwright 모바일 가로 오버플로 검증** (서버 실행 중일 때)

390px 폭으로 `/` 로드 → `+ 분석`(`#analysis-toggle`) 클릭 → 다음을 확인:
- `document.documentElement.scrollWidth <= document.documentElement.clientWidth` (가로 오버플로 없음)
- 입력 폼이 세로 스택(URL/provider/mode/버튼 각 줄)
- 데스크톱 폭(1280)에서 폼 한 줄 유지
(서버 미기동 시 controller가 8001 등으로 기동 후 캡처)

- [ ] **Step 3: (실패 시) systematic-debugging으로 격리 후 수정·재실행**

전부 통과 + 오버플로 없으면 완료.

---

## 수동 검증 (실기기 iOS Safari)
- 검색창·URL 입력 포커스 시 화면이 확대되지 않음.
- `+ 분석` 펼친 입력 폼이 가로폭에 맞게 세로 정렬.

## Self-Review 결과
- **Spec 커버리지:** 1) 폼 세로 스택(T1), 2) iOS 줌 방지(T2), 테스트(각 Step1 + T3), 비목표 준수(다른 partial·safe-area 제외, 데스크톱 무변경) ✅
- **플레이스홀더:** 없음 — 모든 edit에 exact old/new, 테스트 실제 코드.
- **일관성:** `flex flex-col md:flex-row`, `md:flex-1`, `max-width: 767px`/`font-size: 16px` 마커가 spec·테스트·구현에서 일치.
