# 상세 요약 UI 개선 5종 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세 요약 모달의 가독성(접기·간격)·노트 열기 UX·사이드바 리사이즈·입력 영역 폭·챕터 한국어화를 개선한다.

**Architecture:** 챕터 한국어화는 `resolve_chapters`에 한글 판별 + 번역 분기를 추가하고 프로바이더에 `translate_chapters`를 둔다(네이티브 타임스탬프 보존). 나머지는 템플릿/JS 변경(모달 `<details>` 접기, 카드 클릭 오픈, base.html 사이드바 드래그·입력 폭).

**Tech Stack:** FastAPI + HTMX + Jinja2 + Tailwind, Anthropic/OpenAI SDK, pytest. 브랜치 `feature/lilys-detailed-summary`.

---

## Task 1: 챕터 한글 판별 + resolve 분기 + base 기본 translate (chapters.py, base.py)

**Files:**
- Modify: `services/chapters.py`, `services/ai/base.py`
- Test: `tests/test_chapters.py`

- [ ] **Step 1: Add failing tests** — END of `tests/test_chapters.py`

```python
def test_labels_are_korean():
    from services.chapters import _labels_are_korean
    assert _labels_are_korean([{"t": 0, "label": "인트로"}]) is True
    assert _labels_are_korean([{"t": 0, "label": "Intro"}]) is False
    assert _labels_are_korean([{"t": 0, "label": "Intro 도입"}]) is True


@pytest.mark.asyncio
async def test_resolve_keeps_korean_native():
    ai = AsyncMock()
    native = [{"t": 0, "label": "인트로"}]
    chapters, cost, model = await resolve_chapters(native, [], ai)
    assert chapters == native and cost == 0.0
    ai.translate_chapters.assert_not_called()
    ai.generate_chapters.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_translates_nonkorean_native():
    ai = AsyncMock()
    ai.translate_chapters.return_value = ([{"t": 0, "label": "인트로"}], 0.01, "m")
    native = [{"t": 0, "label": "Intro"}]
    chapters, cost, model = await resolve_chapters(native, [], ai)
    assert chapters == [{"t": 0, "label": "인트로"}] and cost == 0.01
    ai.translate_chapters.assert_awaited_once_with(native)
    ai.generate_chapters.assert_not_called()
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_chapters.py -k "labels_are_korean or translates_nonkorean" -v`
Expected: FAIL (`_labels_are_korean` ImportError / translate branch missing).

- [ ] **Step 3a: Implement in `services/chapters.py`** — replace the file's top + `resolve_chapters`:

```python
import re
from services.extractor import segments_to_transcript

_HANGUL = re.compile(r'[가-힣]')


def _labels_are_korean(chapters: list[dict]) -> bool:
    """챕터 라벨에 한글이 하나라도 있으면 한국어로 간주."""
    text = " ".join(str(c.get("label", "")) for c in chapters)
    return bool(_HANGUL.search(text))


async def resolve_chapters(
    native_chapters: list[dict] | None,
    segments: list[dict],
    ai,
) -> tuple[list[dict], float, str]:
    """네이티브 챕터 우선. 비한국어 라벨이면 번역, 없으면 AI 생성."""
    if native_chapters:
        if _labels_are_korean(native_chapters):
            return native_chapters, 0.0, ""
        return await ai.translate_chapters(native_chapters)
    if not segments:
        return [], 0.0, ""
    transcript = segments_to_transcript(segments)
    return await ai.generate_chapters(transcript)
```
(Preserve any existing module docstring/imports already present; the key additions are `re`, `_HANGUL`, `_labels_are_korean`, and the new branch in `resolve_chapters`.)

- [ ] **Step 3b: Add default to `services/ai/base.py`** — inside class `AIProvider`, after `generate_chapters`:

```python
    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        """챕터 라벨을 한국어로 번역. 기본은 원본 그대로(프로바이더가 오버라이드)."""
        return chapters, 0.0, ""
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_chapters.py -v`
Expected: PASS (new + existing; `test_resolve_uses_native_when_present` uses a Korean label so it still returns native).

- [ ] **Step 5: Commit**

```bash
git add services/chapters.py services/ai/base.py tests/test_chapters.py
git commit -m "feat: translate non-korean native chapters to korean in resolve_chapters"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 2: translate_chapters 구현 (claude.py + openai_provider.py)

**Files:**
- Modify: `services/ai/claude.py`, `services/ai/openai_provider.py`
- Test: `tests/test_claude_provider.py`

- [ ] **Step 1: Add failing test** — END of `tests/test_claude_provider.py`

```python
@pytest.mark.asyncio
async def test_translate_chapters(provider):
    import json
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(
        {"chapters": [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]}, ensure_ascii=False))]
    resp.usage = MagicMock(input_tokens=10, output_tokens=10)
    with patch.object(provider._client.messages, "create", new_callable=AsyncMock, return_value=resp):
        chapters, cost, model = await provider.translate_chapters(
            [{"t": 0, "label": "Intro"}, {"t": 90, "label": "Body"}])
    assert chapters == [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]
    assert cost > 0


@pytest.mark.asyncio
async def test_translate_chapters_empty_returns_empty(provider):
    chapters, cost, model = await provider.translate_chapters([])
    assert chapters == [] and cost == 0.0
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `python -m pytest tests/test_claude_provider.py -k translate_chapters -v`
Expected: FAIL (no `translate_chapters` on ClaudeProvider).

- [ ] **Step 3a: Add prompt + method to `services/ai/claude.py`** — add the constant after `CHAPTERS_PROMPT`:

```python
TRANSLATE_CHAPTERS_PROMPT = """다음 영상 챕터 목록의 각 label을 자연스러운 한국어로 번역하세요.
t(시작 시각, 초)는 그대로 두고 label만 번역합니다.

챕터: {chapters}

JSON으로만 응답하세요:
{{"chapters": [{{"t": 0, "label": "번역된 제목"}}]}}"""
```
and add this method to `ClaudeProvider` (next to `generate_chapters`):

```python
    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        model = config.CLAUDE_MODELS["tier2"]
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(chapters=json.dumps(chapters, ensure_ascii=False))
        resp = await self._client.messages.create(
            model=model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        cost = _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        try:
            translated = _build_chapters(_parse_json(resp.content[0].text))
        except (json.JSONDecodeError, ValueError, TypeError):
            translated = []
        return (translated or chapters), cost, model  # 번역 실패 시 원본 유지
```

- [ ] **Step 3b: Mirror in `services/ai/openai_provider.py`** — add `TRANSLATE_CHAPTERS_PROMPT` to the import from `services.ai.claude`, then add:

```python
    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        model = config.GPT_MODELS["tier2"]
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(chapters=json.dumps(chapters, ensure_ascii=False))
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        cost = _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        try:
            translated = _build_chapters(json.loads(resp.choices[0].message.content))
        except (json.JSONDecodeError, ValueError, TypeError):
            translated = []
        return (translated or chapters), cost, model
```
(The import line already pulls `_build_chapters` from claude; just add `TRANSLATE_CHAPTERS_PROMPT`.)

- [ ] **Step 4: Run, confirm PASS**

Run: `python -m pytest tests/test_claude_provider.py tests/test_openai_provider.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ai/claude.py services/ai/openai_provider.py tests/test_claude_provider.py
git commit -m "feat: translate_chapters on claude/openai providers"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Task 3: 노트 카드 제목/본문 클릭 오픈 + "전체 보기" 제거 (note_card.html)

**Files:**
- Modify: `templates/partials/note_card.html`
- 검증: 브라우저 (단위 테스트 없음)

- [ ] **Step 1: Make content area clickable** — replace line 4 `<div class="flex-1">` with:

```html
  <div class="flex-1"
       hx-get="/api/items/{{ note.id }}/detail"
       hx-target="#note-modal"
       hx-swap="innerHTML">
```

- [ ] **Step 2: Remove the "전체 보기" button** — delete this block (currently lines 42–45):

```html
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] hover:border-[#A8CBB2] transition-colors dark:bg-gray-700"
            hx-get="/api/items/{{ note.id }}/detail"
            hx-target="#note-modal"
            hx-swap="innerHTML">전체 보기</button>
```
(Keep the project `<select>`, "상세 정리", and ".md 열기" controls — they remain in the right-hand column and must NOT open the modal.)

- [ ] **Step 3: Sanity render**

Run: `python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print(c.get('/api/items?topic=').status_code)"`
Expected: `200` (note list renders without Jinja error).

- [ ] **Step 4: Commit**

```bash
git add templates/partials/note_card.html
git commit -m "feat: open note modal on card title/body click, drop 전체 보기 button"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 5: Browser verify (manual, after all tasks)** — clicking a card's title/summary opens the detail modal; clicking the project select / .md 열기 / 상세 정리 does NOT open it.

---

## Task 4: 모달 H2 접기/펼치기 + 문단 간격 (note_detail_modal.html)

**Files:**
- Modify: `templates/partials/note_detail_modal.html`
- 검증: 브라우저

- [ ] **Step 1: Replace the 계층 본문 block** — find the `<!-- 계층 본문 -->` block (currently a `<div class="mb-4 space-y-4"> {% for sec in sec_list %} ... </div>`) and replace the WHOLE block with:

```html
    <!-- 계층 본문 -->
    <div class="mb-4 space-y-6">
      {% for sec in sec_list %}
      {% set sec_idx = loop.index %}
      <details open id="sec-{{ sec_idx }}" class="group">
        <summary class="list-none [&::-webkit-details-marker]:hidden cursor-pointer flex items-center gap-2 text-[15px] font-bold text-[#1F2937] dark:text-gray-100 mb-2">
          <span class="text-gray-400 text-[11px] transition-transform group-open:rotate-90">▶</span>
          <span class="flex-1">{{ sec.heading }}</span>
          {% if sec.t is defined and video_id %}<button type="button" onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ sec.t }})" class="text-[11px] font-mono text-[#1F6F4A] dark:text-[#34A66A] hover:underline">⏱{{ "%d:%02d:%02d"|format(sec.t // 3600, sec.t % 3600 // 60, sec.t % 60) if sec.t >= 3600 else "%d:%02d"|format(sec.t // 60, sec.t % 60) }}</button>{% endif %}
        </summary>
        <div class="space-y-3 pl-4">
          {% for sub in sec.subsections %}
          <div id="sec-{{ sec_idx }}-{{ loop.index }}">
            <h3 class="text-[13px] font-semibold text-[#374151] dark:text-gray-200 mb-1.5">{{ sub.heading }}</h3>
            <ul class="space-y-1.5">
              {% for it in sub["items"] %}
              <li class="text-[13px] text-gray-700 dark:text-gray-300">
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
              </li>
              {% endfor %}
            </ul>
          </div>
          {% endfor %}
        </div>
      </details>
      {% endfor %}
    </div>
```
Key changes vs current: outer `space-y-4`→`space-y-6` (문단 간격 ↑); each section is `<details open class="group">`; the H2 is now a `<summary>` with a chevron (`group-open:rotate-90`) and marker hidden; the section `⏱` button adds `event.preventDefault(); event.stopPropagation();` so clicking it seeks WITHOUT toggling the fold; subsections wrapped in `<div class="space-y-3 pl-4">`. The TOC block above is unchanged (its `#sec-N` / `#sec-N-M` anchors still match the `id`s here).

- [ ] **Step 2: Sanity render**

Run: `python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print(c.get('/api/items/32/detail').status_code)"`
Expected: `200` (note 32 is an existing detailed youtube note; must render without Jinja error). If note 32 doesn't exist in your DB, any existing detailed youtube note id works; a `200` with non-empty body confirms it.

- [ ] **Step 3: Commit**

```bash
git add templates/partials/note_detail_modal.html
git commit -m "feat: collapsible H2 sections (details) and wider paragraph spacing in modal"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 4: Browser verify (manual)** — H2 제목 클릭 시 접힘/펼침(셰브론 회전), 기본 펼침; `⏱` 클릭은 영상 이동만 하고 접힘 토글 안 함; 섹션/항목 간격이 넓어짐.

---

## Task 5: 사이드바 드래그 리사이즈 (base.html)

**Files:**
- Modify: `templates/base.html`
- 검증: 브라우저

- [ ] **Step 1: Make the aside resizable + add a drag handle** — in `base.html` change the `<aside class="w-52 ...">` opening tag to (remove `w-52`, add id + inline width):

```html
  <aside id="sidebar" style="width:208px" class="border-r border-[#E2E8E4] bg-white flex flex-col dark:bg-gray-900 dark:border-gray-700 flex-shrink-0">
```
Immediately AFTER the `</aside>` closing tag (and before `<!-- MAIN -->`), insert the handle:

```html
  <!-- SIDEBAR RESIZER -->
  <div id="sidebar-resizer" class="w-1 cursor-col-resize bg-transparent hover:bg-[#1F6F4A]/40 flex-shrink-0"></div>
```

- [ ] **Step 2: Add resize JS** — inside the existing `<script>` block in `base.html` (right after the opening `<script>` tag on the `toggleTheme` line's file, i.e. as the first statements in the block), add:

```javascript
(function initSidebarResize() {
  const sb = document.getElementById('sidebar');
  const rz = document.getElementById('sidebar-resizer');
  if (!sb || !rz) return;
  const clamp = w => Math.min(480, Math.max(160, w));
  const saved = parseInt(localStorage.getItem('sidebarWidth'), 10);
  if (saved) sb.style.width = clamp(saved) + 'px';
  let dragging = false;
  rz.addEventListener('mousedown', e => { dragging = true; document.body.style.userSelect = 'none'; e.preventDefault(); });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    sb.style.width = clamp(e.clientX - sb.getBoundingClientRect().left) + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false; document.body.style.userSelect = '';
    localStorage.setItem('sidebarWidth', parseInt(sb.style.width, 10));
  });
})();
```

- [ ] **Step 3: Sanity render**

Run: `python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print(c.get('/').status_code)"`
Expected: `200`.

- [ ] **Step 4: Commit**

```bash
git add templates/base.html
git commit -m "feat: drag-resizable sidebar with localStorage persistence"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 5: Browser verify (manual)** — 사이드바 우측 경계 드래그로 폭 조절(160–480px), 새로고침 후 폭 유지.

---

## Task 6: Source 입력 밴드 60% 폭 (base.html)

**Files:**
- Modify: `templates/base.html`
- 검증: 브라우저

- [ ] **Step 1: Constrain #input-panel to 60% centered** — change the `#input-panel` opening div:

```html
<div id="input-panel" class="w-[60%] mx-auto bg-[#EAF4EE] border-b border-[#E2E8E4] px-5 py-3 rounded-b-xl dark:bg-[#14291E] dark:border-gray-700">
```
(Added `w-[60%] mx-auto` so the band itself is 60% wide and centered; `rounded-b-xl` softens the now-floating band. Everything inside — the included `input_*.html` form — is unchanged.)

- [ ] **Step 2: Sanity render**

Run: `python -c "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); print(c.get('/').status_code)"`
Expected: `200`.

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "feat: constrain source input band to 60% width centered"
```
End body with: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

- [ ] **Step 4: Browser verify (manual)** — 입력 밴드가 화면 중앙 60% 폭으로 표시.

---

## 최종 검증

- [ ] `python -m pytest -q` — 전체 통과(신규 실패 없음).
- [ ] 브라우저: 카드 클릭 오픈/전체보기 제거, 모달 H2 접기·간격, 사이드바 리사이즈+복원, 입력 밴드 60%, (youtube 재분석/타임라인 생성 시) 챕터 한국어.
