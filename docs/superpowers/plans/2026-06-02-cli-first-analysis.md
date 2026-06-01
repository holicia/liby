# CLI-first Analysis Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** liby가 모든 LLM 호출을 로컬 `agent-runner-bridge` Docker 게이트웨이(127.0.0.1:8787)로 보내, 구독 인증(Claude Pro / ChatGPT Plus)으로 분석을 돌려서 API 비용을 0에 가깝게 만든다.

**Architecture:** 새 `BridgeProvider`가 `AIProvider`를 구현하고, httpx 기반 `bridge_client.run_agent`로 `POST /v1/runs`→폴링→결과 파싱. transport-무관 헬퍼(청킹·JSON 파싱·빌더)는 `services/ai/chunking.py`로 모아 `claude.py`/`bridge.py`가 공유. `get_provider`가 `claude-cli`/`codex-cli`로 라우팅하고, default가 `claude-cli`.

**Tech Stack:** Python 3.13 / FastAPI / httpx (async) / pytest + pytest-asyncio / SQLite (aiosqlite) / Jinja2 + Tailwind / agent-runner-bridge REST.

**Spec:** `docs/superpowers/specs/2026-06-02-cli-first-analysis-design.md`

**Branch:** `feature/cli-first-bridge-2026-06-02` (생성 후 작업; PR 없이 master로 fast-forward 머지 — 기존 패턴)

---

## File Map

**Create:**
- `services/ai/chunking.py` — 공유 헬퍼 모음(transport-무관)
- `services/ai/bridge_client.py` — HTTP 클라이언트 + dataclasses + `BridgeError`
- `services/ai/bridge.py` — `BridgeProvider(adapter)` AIProvider 구현
- `tests/test_chunking.py` — 재사용 헬퍼 import + 동작 검증
- `tests/test_bridge_client.py` — httpx MockTransport 기반 단위 테스트
- `tests/test_bridge_provider.py` — bridge_client mock + summarize/chunking/chapter 통합

**Modify:**
- `config.py` — bridge env + default provider
- `services/ai/__init__.py` — `claude-cli`/`codex-cli` 라우팅
- `services/storage.py` — `aggregate_daily_costs` / `aggregate_monthly_costs`에 cli 키 추가
- `services/ai/claude.py` — chunking.py가 이미 가진 것들을 거기서 import (회귀 없음 확인)
- `templates/partials/input_youtube.html` — provider `<select>`에 cli 두 옵션
- `templates/partials/input_pdf.html` — 동일
- `templates/partials/input_text.html` — 동일
- `templates/partials/input_code.html` — 동일
- `templates/partials/input_markdown.html` — 동일
- `templates/partials/api_cost.html` — 사이드바 위젯에 cli 두 줄 추가
- `templates/usage.html` — 차트 4스택, 누적 카드 4개
- `routers/settings.py::usage_report` — `claude_cli_count`/`codex_cli_count` 컨텍스트
- `.env.example` — 새 환경변수 5종
- `tests/test_storage.py` — 4-provider 집계 검증 추가
- `tests/test_routes_partials.py` — usage 페이지 4 provider markup 검증

**Tests existing — assert no regression:**
- `tests/test_extractor.py`, `tests/test_claude_provider.py`, `tests/test_openai_provider.py`, `tests/test_fallback_provider.py`

---

## Task 1: 분기 생성 + 셋업

**Files:** 없음 (git operation)

- [ ] **Step 1: 새 브랜치 분기**

```bash
git checkout master
git pull --ff-only origin master 2>/dev/null || true
git checkout -b feature/cli-first-bridge-2026-06-02
```

- [ ] **Step 2: 전체 테스트 베이스라인**

Run: `python -m pytest -q`
Expected: PASS (현재 160/160)

기록만 — 진행 중 깨지는지 회귀 확인 기준선.

---

## Task 2: `services/ai/chunking.py` — 공유 헬퍼 모듈

**Files:**
- Create: `services/ai/chunking.py`
- Test: `tests/test_chunking.py`

이 파일은 transport에 무관한 헬퍼들을 한 곳으로 모은다. 신규 헬퍼는 만들지 않고 **기존 함수에 대한 thin re-export**로 시작한다 — 회귀 위험 0.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_chunking.py`:

```python
def test_chunking_exports_helpers_for_bridge_provider():
    """bridge provider가 필요로 하는 모든 헬퍼가 chunking에서 import 가능해야 한다."""
    from services.ai import chunking
    # transport-무관 유틸리티
    assert callable(chunking.chunk_for_llm)
    assert callable(chunking.chunk_range_hint)
    assert callable(chunking.extract_json)
    assert callable(chunking.build_paragraphs)
    assert callable(chunking.build_sections)
    assert callable(chunking.build_chapters)
    assert callable(chunking.build_refs)
    assert callable(chunking.renumber_sections)
    assert callable(chunking.to_t)
    # 상수
    assert chunking.CHUNK_THRESHOLD == 18000
    assert "조각" in chunking.SUMMARY_MERGE_PROMPT


def test_chunking_chunk_for_llm_short_text_returns_single_chunk():
    from services.ai.chunking import chunk_for_llm
    text = "한 줄짜리\n짧은 텍스트"
    assert chunk_for_llm(text) == [text]


def test_chunking_extract_json_strips_code_fence():
    from services.ai.chunking import extract_json
    raw = '```json\n{"title": "Test"}\n```'
    assert extract_json(raw) == {"title": "Test"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_chunking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.ai.chunking'`

- [ ] **Step 3: chunking.py 작성**

Create `services/ai/chunking.py`:

```python
"""Transport-무관 분석 헬퍼.

bridge·claude·openai_provider 등 모든 AIProvider 구현체가 공유한다.
원본 함수들은 historical reason으로 services.extractor와 services.ai.claude에
흩어져 있어, 여기서 깔끔한 이름으로 re-export한다.
"""
from services.extractor import _chunk_for_llm as chunk_for_llm
from services.extractor import _chunk_range_hint as chunk_range_hint
from services.ai.claude import (
    _parse_json as extract_json,
    _build_paragraphs as build_paragraphs,
    _build_sections as build_sections,
    _build_chapters as build_chapters,
    _build_refs as build_refs,
    _renumber_sections as renumber_sections,
    _to_t as to_t,
    SUMMARY_MERGE_PROMPT,
    CHUNK_THRESHOLD,
)

__all__ = [
    "chunk_for_llm", "chunk_range_hint", "extract_json",
    "build_paragraphs", "build_sections", "build_chapters",
    "build_refs", "renumber_sections", "to_t",
    "SUMMARY_MERGE_PROMPT", "CHUNK_THRESHOLD",
]
```

- [ ] **Step 4: 테스트 통과 확인 + 회귀 확인**

Run: `python -m pytest tests/test_chunking.py tests/test_extractor.py tests/test_claude_provider.py -v`
Expected: PASS (신규 3 + 기존 그대로)

Run: `python -m pytest -q`
Expected: 163 passed (160 + 3 신규)

- [ ] **Step 5: 커밋**

```bash
git add services/ai/chunking.py tests/test_chunking.py
git commit -m "feat: chunking.py shared helpers for AI providers

청킹·JSON 파싱·result builder 헬퍼를 한 모듈로 모아 bridge provider도
재사용할 수 있게. 원본 함수 위치는 호환 위해 그대로 두고 re-export."
```

---

## Task 3: `services/ai/bridge_client.py` — HTTP 클라이언트

**Files:**
- Create: `services/ai/bridge_client.py`
- Test: `tests/test_bridge_client.py`

bridge `POST /v1/runs` + 폴링 + JSON 응답 정규화. 외부 의존: httpx (이미 deps).

- [ ] **Step 1: dataclass + 에러 테스트 작성**

Create `tests/test_bridge_client.py`:

```python
import json
import pytest
import httpx
from services.ai.bridge_client import (
    BridgeUsage, BridgeRunResult, BridgeError, run_agent,
)


def test_bridge_usage_defaults():
    u = BridgeUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.total_cost_usd == 0.0


def test_bridge_run_result_holds_fields():
    r = BridgeRunResult(summary="ok", session_id="s1",
                        usage=BridgeUsage(input_tokens=10, output_tokens=20))
    assert r.summary == "ok"
    assert r.usage.input_tokens == 10


def test_bridge_error_carries_status_and_exit_code():
    e = BridgeError(status="failed", exit_code=1, summary="boom")
    assert e.status == "failed"
    assert e.exit_code == 1
    assert "boom" in str(e)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_bridge_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: dataclass + 에러 구현**

Create `services/ai/bridge_client.py`:

```python
"""agent-runner-bridge HTTP 클라이언트.

POST /v1/runs로 작업 생성 → status 폴링 → terminal 도달 시 결과/에러 반환.
구독 인증 사용 시 usage.total_cost_usd는 보통 0.
"""
import asyncio
from dataclasses import dataclass, field
import httpx
import config


@dataclass
class BridgeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass
class BridgeRunResult:
    summary: str
    session_id: str | None
    usage: BridgeUsage = field(default_factory=BridgeUsage)


class BridgeError(RuntimeError):
    def __init__(self, status: str, exit_code: int | None, summary: str) -> None:
        self.status = status
        self.exit_code = exit_code
        self.summary = summary
        super().__init__(f"bridge {status} (exit {exit_code}): {summary[:200]}")


_POLL_INTERVAL_SEC = 1.5
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}


async def run_agent(
    prompt: str,
    *,
    adapter: str,
    cwd: str | None = None,
    model: str | None = None,
    timeout_sec: int = 900,
) -> BridgeRunResult:
    if not config.BRIDGE_TOKEN:
        raise RuntimeError("BRIDGE_TOKEN 미설정: .env에 BRIDGE_TOKEN을 설정하세요.")
    headers = {"Authorization": f"Bearer {config.BRIDGE_TOKEN}"}
    body: dict = {"adapter": adapter, "prompt": prompt, "timeoutSec": timeout_sec}
    if cwd:
        body["cwd"] = cwd
    if model:
        body["model"] = model
    async with httpx.AsyncClient(base_url=config.BRIDGE_BASE_URL, timeout=30.0) as c:
        create = await c.post("/v1/runs", json=body, headers=headers)
        if create.status_code == 402:
            raise BridgeError("budget_exceeded", None, create.text)
        if create.status_code == 401:
            raise BridgeError("unauthorized", None, "bridge 인증 실패: BRIDGE_TOKEN 확인")
        create.raise_for_status()
        run = create.json()
        run_id = run["id"]
        # 폴링
        deadline_loops = int(timeout_sec / _POLL_INTERVAL_SEC) + 5
        for _ in range(deadline_loops):
            await asyncio.sleep(_POLL_INTERVAL_SEC)
            poll = await c.get(f"/v1/runs/{run_id}", headers=headers)
            poll.raise_for_status()
            data = poll.json()
            status = data.get("status")
            if status in _TERMINAL_STATUSES:
                summary = data.get("summary") or ""
                if status != "succeeded":
                    raise BridgeError(status, data.get("exitCode"), summary)
                usage_raw = data.get("usage") or {}
                usage = BridgeUsage(
                    input_tokens=int(usage_raw.get("inputTokens", 0) or 0),
                    output_tokens=int(usage_raw.get("outputTokens", 0) or 0),
                    total_cost_usd=float(usage_raw.get("totalCostUsd", 0.0) or 0.0),
                )
                return BridgeRunResult(
                    summary=summary,
                    session_id=data.get("sessionId"),
                    usage=usage,
                )
        raise BridgeError("polling_timeout", None,
                          f"bridge가 {timeout_sec}s 안에 응답 안 함")
```

`config.py`는 아직 BRIDGE_TOKEN/BRIDGE_BASE_URL이 없으므로 ImportError가 날 것 — 다음 Step 4에서 추가.

- [ ] **Step 4: config.py에 bridge 환경변수 추가**

Edit `config.py`, 기존 `DEFAULT_AI_PROVIDER` 라인 바로 아래에 추가 (변경 전 default는 그대로 `"claude"` 유지 — Task 9에서 `claude-cli`로 변경):

```python
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MONTHLY_LIMIT_USD: float = float(os.getenv("CLAUDE_MONTHLY_LIMIT_USD", "2.00"))
GPT_MONTHLY_LIMIT_USD: float = float(os.getenv("GPT_MONTHLY_LIMIT_USD", "2.00"))
DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "claude")
BRIDGE_BASE_URL: str = os.getenv("BRIDGE_BASE_URL", "http://127.0.0.1:8787")
BRIDGE_TOKEN: str = os.getenv("BRIDGE_TOKEN", "")
BRIDGE_CWD: str = os.getenv("BRIDGE_CWD", "/workspace/liby-runs")
BRIDGE_TIMEOUT_SEC: int = int(os.getenv("BRIDGE_TIMEOUT_SEC", "900"))
VAULT_PATH: str = os.getenv("VAULT_PATH", "./vault")
```

- [ ] **Step 5: dataclass 테스트 통과 확인**

Run: `python -m pytest tests/test_bridge_client.py -v`
Expected: PASS (위 3개 테스트)

- [ ] **Step 6: HTTP mock 테스트 작성 — 성공 경로**

Append to `tests/test_bridge_client.py`:

```python
@pytest.mark.asyncio
async def test_run_agent_success_returns_result(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-123")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    seen_auth = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth[req.url.path] = req.headers.get("authorization")
        if req.method == "POST" and req.url.path == "/v1/runs":
            return httpx.Response(202, json={"id": "run-1", "status": "queued"})
        if req.method == "GET" and req.url.path == "/v1/runs/run-1":
            return httpx.Response(200, json={
                "id": "run-1", "status": "succeeded",
                "summary": '{"title":"hi"}', "sessionId": "sess-1",
                "usage": {"inputTokens": 100, "outputTokens": 50, "totalCostUsd": 0.0},
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # patch AsyncClient(...) → use transport
    import services.ai.bridge_client as bc
    orig_client = bc.httpx.AsyncClient
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig_client(transport=transport, **kw))

    result = await bc.run_agent("hi", adapter="claude")
    assert result.summary == '{"title":"hi"}'
    assert result.session_id == "sess-1"
    assert result.usage.input_tokens == 100
    assert result.usage.total_cost_usd == 0.0
    assert seen_auth["/v1/runs"] == "Bearer t-123"
```

핵심: `_POLL_INTERVAL_SEC`을 monkeypatch로 줄여 테스트가 빠르게.

- [ ] **Step 7: 성공 경로 통과 확인**

Run: `python -m pytest tests/test_bridge_client.py::test_run_agent_success_returns_result -v`
Expected: PASS

- [ ] **Step 8: 실패 경로 테스트 추가**

Append to `tests/test_bridge_client.py`:

```python
@pytest.mark.asyncio
async def test_run_agent_failed_status_raises_bridge_error(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json={"id": "r", "status": "queued"})
        return httpx.Response(200, json={
            "id": "r", "status": "failed", "exitCode": 1,
            "summary": "boom", "usage": {},
        })

    import services.ai.bridge_client as bc
    monkeypatch.setattr(bc, "_POLL_INTERVAL_SEC", 0.01, raising=False)
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))

    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "failed"
    assert exc.value.exit_code == 1


@pytest.mark.asyncio
async def test_run_agent_budget_exceeded_402(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    monkeypatch.setattr(config, "BRIDGE_BASE_URL", "http://bridge.test")
    def handler(req): return httpx.Response(402, text="budget exhausted")
    import services.ai.bridge_client as bc
    orig = bc.httpx.AsyncClient
    monkeypatch.setattr(bc.httpx, "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(BridgeError) as exc:
        await bc.run_agent("hi", adapter="claude")
    assert exc.value.status == "budget_exceeded"


@pytest.mark.asyncio
async def test_run_agent_missing_token_raises():
    import config as c
    saved = c.BRIDGE_TOKEN
    c.BRIDGE_TOKEN = ""
    try:
        with pytest.raises(RuntimeError, match="BRIDGE_TOKEN"):
            await run_agent("hi", adapter="claude")
    finally:
        c.BRIDGE_TOKEN = saved
```

- [ ] **Step 9: 실패 경로 통과 확인**

Run: `python -m pytest tests/test_bridge_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 10: 커밋**

```bash
git add services/ai/bridge_client.py tests/test_bridge_client.py config.py
git commit -m "feat: bridge_client for agent-runner-bridge HTTP transport

run_agent(prompt, adapter)이 POST /v1/runs → 폴링 → BridgeRunResult.
구독 인증으로 cost_usd=0 케이스 포함, 402/401/timed_out/failed 모두
BridgeError로 매핑. config에 BRIDGE_* 4종 추가."
```

---

## Task 4: `services/ai/bridge.py` — BridgeProvider

**Files:**
- Create: `services/ai/bridge.py`
- Test: `tests/test_bridge_provider.py`

`AIProvider` 추상의 모든 메서드를 bridge_client + chunking 헬퍼로 구현.

- [ ] **Step 1: 실패 테스트 작성 — 기본 wiring**

Create `tests/test_bridge_provider.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
import config


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


def test_bridge_provider_init_requires_valid_adapter():
    from services.ai.bridge import BridgeProvider
    BridgeProvider(adapter="claude")  # ok
    BridgeProvider(adapter="codex")   # ok
    with pytest.raises(ValueError, match="adapter"):
        BridgeProvider(adapter="invalid")


def test_bridge_provider_name_reflects_adapter():
    from services.ai.bridge import BridgeProvider
    assert BridgeProvider(adapter="claude").name() == "claude-cli"
    assert BridgeProvider(adapter="codex").name() == "codex-cli"


def test_bridge_provider_missing_token_raises(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "")
    from services.ai.bridge import BridgeProvider
    with pytest.raises(RuntimeError, match="BRIDGE_TOKEN"):
        BridgeProvider(adapter="claude")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: BridgeProvider 골격 + 생성자**

Create `services/ai/bridge.py`:

```python
"""BridgeProvider: 모든 LLM 호출을 agent-runner-bridge로 위임.

구독 인증(Claude Pro / ChatGPT Plus)이 설정된 bridge에 연결되어 있으면
cost_usd=0으로 동일한 분석 결과를 받을 수 있다.
"""
import json
from services.ai.base import AIProvider, SummaryResult
from services.ai import chunking
from services.ai import bridge_client
from services.ai.claude import (
    TIER2_PROMPT, TIER2_CODE_PROMPT, DETAILED_PROMPT,
    CHAPTERS_PROMPT, TRANSLATE_CHAPTERS_PROMPT,
)
import config

_VALID_ADAPTERS = {"claude", "codex"}


class BridgeProvider(AIProvider):
    def __init__(self, adapter: str) -> None:
        if adapter not in _VALID_ADAPTERS:
            raise ValueError(
                f"adapter는 {sorted(_VALID_ADAPTERS)} 중 하나여야 합니다: {adapter}"
            )
        if not config.BRIDGE_TOKEN:
            raise RuntimeError("BRIDGE_TOKEN 미설정: .env에 BRIDGE_TOKEN을 설정하세요.")
        self._adapter = adapter

    def name(self) -> str:
        return f"{self._adapter}-cli"

    async def summarize(
        self, text: str, source_type: str, mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        raise NotImplementedError  # Step 5에서 구현

    async def run_tier3(self, summary: str) -> SummaryResult:
        raise NotImplementedError  # Step 9에서 구현

    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        raise NotImplementedError  # Step 11에서 구현

    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        raise NotImplementedError  # Step 13에서 구현
```

- [ ] **Step 4: wiring 통과 확인**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: summarize 단일(short text) 테스트 작성**

Append to `tests/test_bridge_provider.py`:

```python
@pytest.mark.asyncio
async def test_bridge_summarize_short_text_single_run(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    fake = AsyncMock(return_value=bc.BridgeRunResult(
        summary=(
            '{"title":"제목","language":"ko","word_count":10,'
            '"reading_time_min":1,"sections":[],'
            '"summary":"요약","paragraphs":[{"text":"문단1","refs":[]}],'
            '"tags":["t1"],"suggested_topic":"주제"}'
        ),
        session_id="s1",
        usage=bc.BridgeUsage(input_tokens=200, output_tokens=80, total_cost_usd=0.0),
    ))
    monkeypatch.setattr(bc, "run_agent", fake)

    p = BridgeProvider(adapter="claude")
    result = await p.summarize("짧은 텍스트", "youtube", "quick", [])

    assert result.title == "제목"
    assert result.summary == "요약"
    assert result.paragraphs == [{"text": "문단1", "refs": []}]
    assert result.cost_usd == 0.0
    assert result.models_used == ["claude"]
    fake.assert_awaited_once()
    # adapter가 전달되는지
    kwargs = fake.await_args.kwargs
    assert kwargs["adapter"] == "claude"
```

- [ ] **Step 6: 실패 확인**

Run: `python -m pytest tests/test_bridge_provider.py::test_bridge_summarize_short_text_single_run -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 7: summarize 단일 + 청킹 구현**

Edit `services/ai/bridge.py`, `summarize`와 `_summarize_single` 메서드 추가:

```python
    async def summarize(
        self, text: str, source_type: str, mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        if len(text) <= chunking.CHUNK_THRESHOLD:
            return await self._summarize_single(text, source_type, mode, existing_topics)
        chunks = chunking.chunk_for_llm(text)
        partials: list[SummaryResult] = []
        for chunk in chunks:
            try:
                hint = chunking.chunk_range_hint(chunk)
                partial = await self._summarize_single(
                    chunk, source_type, mode, existing_topics, chunk_info=hint)
                partials.append(partial)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"chunk {len(partials)+1} failed: {e}")
        if not partials:
            raise ValueError("청킹 분석 실패: 모든 chunk 호출 실패")
        return await self._merge_partials(partials, mode)

    async def _summarize_single(
        self, text: str, source_type: str, mode: str,
        existing_topics: list[str], chunk_info: str | None = None,
    ) -> SummaryResult:
        if mode == "detailed":
            template = DETAILED_PROMPT
        else:
            template = TIER2_CODE_PROMPT if source_type == "code" else TIER2_PROMPT
        text_prefix = (
            f"[조각 정보] 이 입력은 영상의 일부입니다: {chunk_info}. "
            f"모든 sections/items/refs의 t는 반드시 이 범위 안의 [m:ss] 값을 그대로 사용하세요.\n\n"
            if chunk_info else ""
        )
        prompt = template.format(
            text=text_prefix + text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        run = await bridge_client.run_agent(
            prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
            timeout_sec=config.BRIDGE_TIMEOUT_SEC,
        )
        data = chunking.extract_json(run.summary)
        return SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=chunking.build_sections(data),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            insights=data.get("insights"),
            questions_raised=data.get("questions_raised"),
            paragraphs=chunking.build_paragraphs(data),
            cost_usd=run.usage.total_cost_usd,
            models_used=[self._adapter],
        )

    async def _merge_partials(
        self, partials: list[SummaryResult], mode: str,
    ) -> SummaryResult:
        base = partials[0]
        all_paragraphs = [p for prt in partials for p in (prt.paragraphs or [])]
        merged_sections = [s for prt in partials for s in (prt.sections or [])]
        merged_sections.sort(key=lambda s: s.get("t", float("inf")))
        all_sections = chunking.renumber_sections(merged_sections)
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
                run = await bridge_client.run_agent(
                    chunking.SUMMARY_MERGE_PROMPT.format(partials=partials_text),
                    adapter=self._adapter, cwd=config.BRIDGE_CWD,
                    timeout_sec=config.BRIDGE_TIMEOUT_SEC,
                )
                merge_data = chunking.extract_json(run.summary)
                merged_summary = merge_data.get("summary", base.summary)
                total_cost += run.usage.total_cost_usd
                models_used.append(self._adapter)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"summary merge failed, using first partial: {e}")

        return SummaryResult(
            title=base.title, language=base.language,
            word_count=sum(prt.word_count for prt in partials),
            reading_time_min=sum(prt.reading_time_min for prt in partials),
            sections=all_sections, summary=merged_summary,
            key_points=all_key_points, tags=all_tags,
            suggested_topic=base.suggested_topic, summary_mode=mode,
            insights=all_insights or None,
            questions_raised=all_questions or None,
            paragraphs=all_paragraphs, cost_usd=total_cost,
            models_used=models_used,
        )
```

- [ ] **Step 8: summarize 통과 확인**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: summarize 청킹 테스트 + run_tier3 구현**

Append to `tests/test_bridge_provider.py`:

```python
@pytest.mark.asyncio
async def test_bridge_summarize_long_text_triggers_chunking(monkeypatch):
    """CHUNK_THRESHOLD 초과 시 chunk 수 + 1(merge) 호출."""
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc, chunking
    long_text = ("줄\n" * 6000)  # > 18000자
    assert len(long_text) > chunking.CHUNK_THRESHOLD

    def stub_summary(i: int) -> str:
        return (
            f'{{"title":"t{i}","language":"ko","word_count":1,'
            f'"reading_time_min":1,"sections":[],'
            f'"summary":"부분요약 {i}","paragraphs":[],'
            f'"tags":[],"suggested_topic":""}}'
        )

    call_count = {"n": 0}
    async def fake(prompt, **kw):
        call_count["n"] += 1
        i = call_count["n"]
        if "[조각 1]" in prompt:  # merge
            return bc.BridgeRunResult(
                summary='{"summary":"통합 요약"}', session_id=None,
                usage=bc.BridgeUsage())
        return bc.BridgeRunResult(
            summary=stub_summary(i), session_id=None,
            usage=bc.BridgeUsage(input_tokens=10, output_tokens=10))

    monkeypatch.setattr(bc, "run_agent", fake)
    p = BridgeProvider(adapter="claude")
    result = await p.summarize(long_text, "youtube", "quick", [])
    chunks = chunking.chunk_for_llm(long_text)
    assert call_count["n"] == len(chunks) + 1  # partials + merge
    assert result.summary == "통합 요약"
```

`run_tier3` 구현은 `summarize`를 재호출하면 됨 (ClaudeProvider와 동일 패턴):

Edit `services/ai/bridge.py`:

```python
    async def run_tier3(self, summary: str) -> SummaryResult:
        return await self.summarize(summary, "fallback", "detailed", [])
```

- [ ] **Step 10: 청킹 통과 확인**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: PASS (5 tests)

- [ ] **Step 11: chapters 테스트 + 구현**

Append to `tests/test_bridge_provider.py`:

```python
@pytest.mark.asyncio
async def test_bridge_generate_chapters_calls_run_agent(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary='{"chapters":[{"t":0,"label":"intro"},{"t":120,"label":"part1"}]}',
        session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    chapters, cost, model = await p.generate_chapters("자막 텍스트")
    assert chapters == [{"t": 0, "label": "intro"}, {"t": 120, "label": "part1"}]
    assert cost == 0.0
    assert model == "claude"


@pytest.mark.asyncio
async def test_bridge_generate_chapters_bad_json_returns_empty(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary="잘못된 응답", session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    chapters, _, _ = await p.generate_chapters("자막")
    assert chapters == []
```

Edit `services/ai/bridge.py`, `generate_chapters` 구현:

```python
    async def generate_chapters(self, transcript: str) -> tuple[list[dict], float, str]:
        prompt = CHAPTERS_PROMPT.format(transcript=transcript[:14000])
        try:
            run = await bridge_client.run_agent(
                prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
                timeout_sec=config.BRIDGE_TIMEOUT_SEC,
            )
            chapters = chunking.build_chapters(chunking.extract_json(run.summary))
            return chapters, run.usage.total_cost_usd, self._adapter
        except Exception:
            return [], 0.0, self._adapter
```

- [ ] **Step 12: chapters 통과 확인**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: PASS (7 tests)

- [ ] **Step 13: translate_chapters 테스트 + 구현**

Append to `tests/test_bridge_provider.py`:

```python
@pytest.mark.asyncio
async def test_bridge_translate_chapters_empty_input_returns_empty(monkeypatch):
    from services.ai.bridge import BridgeProvider
    p = BridgeProvider(adapter="claude")
    out, cost, model = await p.translate_chapters([])
    assert out == []
    assert cost == 0.0


@pytest.mark.asyncio
async def test_bridge_translate_chapters_translates(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary='{"chapters":[{"t":0,"label":"소개"}]}',
        session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    out, _, _ = await p.translate_chapters([{"t": 0, "label": "intro"}])
    assert out == [{"t": 0, "label": "소개"}]


@pytest.mark.asyncio
async def test_bridge_translate_chapters_failure_returns_original(monkeypatch):
    from services.ai.bridge import BridgeProvider
    from services.ai import bridge_client as bc
    monkeypatch.setattr(bc, "run_agent", AsyncMock(return_value=bc.BridgeRunResult(
        summary="잘못된 응답", session_id=None, usage=bc.BridgeUsage(),
    )))
    p = BridgeProvider(adapter="claude")
    original = [{"t": 0, "label": "intro"}]
    out, _, _ = await p.translate_chapters(original)
    assert out == original
```

Edit `services/ai/bridge.py`, `translate_chapters` 구현:

```python
    async def translate_chapters(self, chapters: list[dict]) -> tuple[list[dict], float, str]:
        if not chapters:
            return [], 0.0, ""
        prompt = TRANSLATE_CHAPTERS_PROMPT.format(
            chapters=json.dumps(chapters, ensure_ascii=False))
        try:
            run = await bridge_client.run_agent(
                prompt, adapter=self._adapter, cwd=config.BRIDGE_CWD,
                timeout_sec=config.BRIDGE_TIMEOUT_SEC,
            )
            translated = chunking.build_chapters(chunking.extract_json(run.summary))
            return (translated or chapters), run.usage.total_cost_usd, self._adapter
        except Exception:
            return chapters, 0.0, self._adapter
```

- [ ] **Step 14: 전체 bridge provider 테스트 통과**

Run: `python -m pytest tests/test_bridge_provider.py -v`
Expected: PASS (10 tests)

Run: `python -m pytest -q`
Expected: 173 passed (163 + 10 신규)

- [ ] **Step 15: 커밋**

```bash
git add services/ai/bridge.py tests/test_bridge_provider.py
git commit -m "feat: BridgeProvider — all LLM calls via agent-runner-bridge

summarize(청킹 포함), run_tier3, generate_chapters, translate_chapters
모두 bridge_client.run_agent로. claude.py의 프롬프트와 chunking.py 헬퍼
재사용. JSON 파싱 실패 시 build_chapters는 빈 리스트, translate는 원본 유지."
```

---

## Task 5: `services/ai/__init__.py` — get_provider 라우팅

**Files:**
- Modify: `services/ai/__init__.py`
- Test: `tests/test_get_provider.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_get_provider.py`:

```python
import pytest
import config


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


def test_get_provider_claude_cli_returns_bridge_claude():
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider("claude-cli")
    assert isinstance(p, BridgeProvider)
    assert p.name() == "claude-cli"


def test_get_provider_codex_cli_returns_bridge_codex():
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider("codex-cli")
    assert isinstance(p, BridgeProvider)
    assert p.name() == "codex-cli"


def test_get_provider_claude_still_returns_api_provider():
    from services.ai import get_provider
    from services.ai.claude import ClaudeProvider
    assert isinstance(get_provider("claude"), ClaudeProvider)


def test_get_provider_gpt_still_returns_api_provider():
    from services.ai import get_provider
    from services.ai.openai_provider import OpenAIProvider
    assert isinstance(get_provider("gpt"), OpenAIProvider)


def test_get_provider_unknown_falls_back():
    from services.ai import get_provider
    from services.ai.fallback import FallbackProvider
    assert isinstance(get_provider("totally-unknown"), FallbackProvider)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_get_provider.py -v`
Expected: FAIL (claude-cli/codex-cli는 현재 fallback으로 떨어짐)

- [ ] **Step 3: get_provider 수정**

Edit `services/ai/__init__.py`:

```python
import config
from services.ai.claude import ClaudeProvider
from services.ai.openai_provider import OpenAIProvider
from services.ai.fallback import FallbackProvider
from services.ai.bridge import BridgeProvider
from services.ai.base import AIProvider

def get_provider(name: str | None = None) -> AIProvider:
    provider_name = name or config.DEFAULT_AI_PROVIDER
    if provider_name == "claude":
        return ClaudeProvider()
    if provider_name == "gpt":
        return OpenAIProvider()
    if provider_name == "claude-cli":
        return BridgeProvider(adapter="claude")
    if provider_name == "codex-cli":
        return BridgeProvider(adapter="codex")
    return FallbackProvider()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_get_provider.py -v`
Expected: PASS (5 tests)

Run: `python -m pytest -q`
Expected: 178 passed (173 + 5 신규)

- [ ] **Step 5: 커밋**

```bash
git add services/ai/__init__.py tests/test_get_provider.py
git commit -m "feat: route claude-cli/codex-cli to BridgeProvider in get_provider"
```

---

## Task 6: `services/storage.py` — 4-provider 집계

**Files:**
- Modify: `services/storage.py:209-272`
- Test: `tests/test_storage.py` (확장)

`aggregate_daily_costs`와 `aggregate_monthly_costs`가 4개 provider 값을 모두 반환하도록 확장. 기존 키(claude, gpt, total)는 호환을 위해 그대로 유지하고 `claude_cli`, `codex_cli` 추가.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_storage.py`:

```python
@pytest.mark.asyncio
async def test_aggregate_daily_costs_includes_cli_buckets(db):
    from services.storage import aggregate_daily_costs
    await record_api_cost(db, provider="claude-cli", model="claude",
                          input_tokens=100, output_tokens=50, cost_usd=0.0)
    await record_api_cost(db, provider="codex-cli", model="codex",
                          input_tokens=200, output_tokens=80, cost_usd=0.0)
    out = await aggregate_daily_costs(db, days=3)
    assert len(out) == 3
    last = out[-1]
    assert "claude_cli" in last
    assert "codex_cli" in last
    assert last["claude_cli"] == pytest.approx(0.0)
    assert last["codex_cli"] == pytest.approx(0.0)
    # 기존 키 유지
    assert "claude" in last and "gpt" in last and "total" in last


@pytest.mark.asyncio
async def test_aggregate_monthly_costs_includes_cli_buckets(db):
    from services.storage import aggregate_monthly_costs
    await record_api_cost(db, provider="claude-cli", model="claude",
                          input_tokens=100, output_tokens=50, cost_usd=0.0)
    out = await aggregate_monthly_costs(db, months=3)
    assert len(out) == 3
    last = out[-1]
    assert "claude_cli" in last and "codex_cli" in last
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_storage.py::test_aggregate_daily_costs_includes_cli_buckets tests/test_storage.py::test_aggregate_monthly_costs_includes_cli_buckets -v`
Expected: FAIL (KeyError on `claude_cli`)

- [ ] **Step 3: aggregate 함수 확장**

Edit `services/storage.py:225-235` (within `aggregate_daily_costs`):

```python
    by_day: dict[str, dict[str, float]] = {}
    for day, provider, cost in rows:
        by_day.setdefault(day, {})[provider] = cost or 0.0

    today_kst = datetime.now(KST).date()
    out: list[dict] = []
    for offset in range(days - 1, -1, -1):
        d = (today_kst - timedelta(days=offset)).strftime("%Y-%m-%d")
        bucket = by_day.get(d, {})
        claude = bucket.get("claude", 0.0)
        gpt = bucket.get("gpt", 0.0)
        claude_cli = bucket.get("claude-cli", 0.0)
        codex_cli = bucket.get("codex-cli", 0.0)
        out.append({
            "date": d,
            "claude": claude, "gpt": gpt,
            "claude_cli": claude_cli, "codex_cli": codex_cli,
            "total": claude + gpt + claude_cli + codex_cli,
        })
    return out
```

Edit `services/storage.py:267-271` (within `aggregate_monthly_costs`):

```python
    for m in reversed(bucket_months):
        bucket = by_month.get(m, {})
        claude = bucket.get("claude", 0.0)
        gpt = bucket.get("gpt", 0.0)
        claude_cli = bucket.get("claude-cli", 0.0)
        codex_cli = bucket.get("codex-cli", 0.0)
        out.append({
            "month": m,
            "claude": claude, "gpt": gpt,
            "claude_cli": claude_cli, "codex_cli": codex_cli,
            "total": claude + gpt + claude_cli + codex_cli,
        })
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS (기존 + 신규 2)

- [ ] **Step 5: 커밋**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: aggregate_*_costs include claude-cli/codex-cli buckets"
```

---

## Task 7: 라우터 — provider 인자 화이트리스트 (검증)

**Files:**
- Modify (확인만): `routers/youtube.py`, `routers/pdf.py`, `routers/text.py`, `routers/code.py`, `routers/markdown.py`
- Test: `tests/test_routes_provider_routing.py` (신규)

라우터들이 `provider: str = Form(...)`로 받기만 하고 별도 화이트리스트가 없는지 확인 (없으면 코드 변경 불필요).

- [ ] **Step 1: 라우터 검증 — provider 화이트리스트 존재 여부**

Run:
```bash
grep -nE "provider.*(in |==|!=)" routers/*.py
```

문자열 비교가 있더라도 `provider` 값을 명시적으로 거부하는 코드가 없으면 통과 — `get_provider`가 fallback으로 처리한다.

- [ ] **Step 2: 통합 테스트 작성**

Create `tests/test_routes_provider_routing.py`:

```python
"""provider=claude-cli로 요청해도 라우터가 BridgeProvider를 받는지 검증."""
import pytest
import config
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch):
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t-test")


@pytest.mark.asyncio
async def test_text_route_accepts_claude_cli_provider(tmp_path, monkeypatch):
    """POST /api/text 가 provider=claude-cli 폼 값을 받아 BridgeProvider로 라우팅."""
    fake = AsyncMock(return_value=SummaryResult(
        title="t", language="ko", word_count=1, reading_time_min=1,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
        paragraphs=[{"text": "x", "refs": []}],
        cost_usd=0.0, models_used=["claude"],
    ))
    with patch("services.ai.bridge.BridgeProvider.summarize", new=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/text", data={
                "text": "안녕하세요. 짧은 입력 텍스트입니다.",
                "provider": "claude-cli", "mode": "quick",
            })
    assert resp.status_code == 200
    fake.assert_awaited()
```

- [ ] **Step 3: 통과 확인**

Run: `python -m pytest tests/test_routes_provider_routing.py -v`
Expected: PASS

만약 라우터가 `provider`를 명시 거부하면 라우터 수정 필요. 그 경우 라우터의 거부 로직을 제거 (allowed list가 있다면 `claude-cli`, `codex-cli` 추가).

- [ ] **Step 4: 커밋**

```bash
git add tests/test_routes_provider_routing.py
git commit -m "test: routes accept claude-cli provider value"
```

---

## Task 8: 분석 폼 5개 — provider `<select>` 옵션 추가

**Files:**
- Modify: `templates/partials/input_youtube.html`
- Modify: `templates/partials/input_pdf.html`
- Modify: `templates/partials/input_text.html`
- Modify: `templates/partials/input_code.html`
- Modify: `templates/partials/input_markdown.html`
- Test: `tests/test_routes_partials.py` (확장)

5개 파일 모두 `<select name="provider">` 블록만 동일하게 교체.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_routes_partials.py`:

```python
@pytest.mark.asyncio
async def test_index_input_forms_offer_cli_providers():
    """5 input partial들이 claude-cli/codex-cli 옵션을 모두 노출해야 한다."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    # 5 폼 각자에 claude-cli/codex-cli option이 있어야 함
    assert resp.text.count('value="claude-cli"') >= 5
    assert resp.text.count('value="codex-cli"') >= 5
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_index_input_forms_offer_cli_providers -v`
Expected: FAIL (0 count)

- [ ] **Step 3: 5개 파일 모두 동일 교체**

각 `templates/partials/input_*.html`의 `<select name="provider">` 블록을 아래로 교체:

```html
  <select name="provider" class="bg-white border border-[#E2E8E4] rounded-lg px-3 py-2.5 text-xs text-gray-500 dark:bg-gray-800">
    <option value="claude-cli">Claude CLI (구독, 무료)</option>
    <option value="codex-cli">Codex CLI (구독, 무료)</option>
    <option value="claude">Claude API ($)</option>
    <option value="gpt">GPT API ($)</option>
  </select>
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add templates/partials/input_*.html tests/test_routes_partials.py
git commit -m "feat: input forms offer Claude/Codex CLI as first options"
```

---

## Task 9: `config.DEFAULT_AI_PROVIDER`를 claude-cli로 변경

**Files:**
- Modify: `config.py:10`
- Test: `tests/test_get_provider.py` (확장)

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_get_provider.py`:

```python
def test_default_provider_is_claude_cli(monkeypatch):
    """get_provider()에 인자 안 주면 BridgeProvider("claude")로 라우팅."""
    monkeypatch.setattr(config, "DEFAULT_AI_PROVIDER", "claude-cli")
    monkeypatch.setattr(config, "BRIDGE_TOKEN", "t")
    from services.ai import get_provider
    from services.ai.bridge import BridgeProvider
    p = get_provider()
    assert isinstance(p, BridgeProvider)
    assert p.name() == "claude-cli"


def test_default_provider_module_default_is_claude_cli():
    """모듈 로드 시 환경변수 없으면 'claude-cli'가 default."""
    import importlib, config as c
    # 환경변수 클린 상태 — 기본값이 claude-cli여야 함
    # (실제 환경에서는 .env가 override 가능)
    src = (open(c.__file__, encoding='utf-8').read())
    assert 'os.getenv("DEFAULT_AI_PROVIDER", "claude-cli")' in src
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_get_provider.py::test_default_provider_module_default_is_claude_cli -v`
Expected: FAIL (default가 아직 "claude")

- [ ] **Step 3: config.py 수정**

Edit `config.py:10`:

```python
DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "claude-cli")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_get_provider.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 커밋**

```bash
git add config.py tests/test_get_provider.py
git commit -m "feat: DEFAULT_AI_PROVIDER -> claude-cli (subscription first)"
```

---

## Task 10: 사이드바 위젯 — CLI 두 줄 추가

**Files:**
- Modify: `routers/settings.py::get_cost_widget` (claude_cli_count, codex_cli_count 컨텍스트 추가)
- Modify: `templates/partials/api_cost.html`
- Test: `tests/test_routes_partials.py` (확장)

CLI는 비용이 0이므로 progress bar 대신 "이번 달 호출 N회" 텍스트로.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_routes_partials.py`:

```python
@pytest.mark.asyncio
async def test_cost_widget_shows_cli_call_counts():
    """사이드바 위젯이 Claude CLI / Codex CLI 호출 횟수를 표시한다."""
    async def fake_monthly(db, provider):
        return {"claude": 0.0, "gpt": 0.0}.get(provider, 0.0)
    async def fake_count(db, provider):
        return {"claude-cli": 12, "codex-cli": 3}.get(provider, 0)
    with patch("services.storage.get_monthly_cost", new=fake_monthly), \
         patch("services.storage.get_monthly_call_count", new=fake_count):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/cost")
    assert resp.status_code == 200
    assert "Claude CLI" in resp.text
    assert "Codex CLI" in resp.text
    assert "12" in resp.text  # 호출 횟수
    assert "3" in resp.text
```

- [ ] **Step 2: storage에 호출 횟수 카운터 추가 (실패 확인)**

Run: `python -m pytest tests/test_routes_partials.py::test_cost_widget_shows_cli_call_counts -v`
Expected: FAIL (`get_monthly_call_count` 없음)

- [ ] **Step 3: `get_monthly_call_count` 추가**

Append to `services/storage.py` (`get_monthly_cost` 다음 위치, 약 line 207):

```python
async def get_monthly_call_count(db_path: str, provider: str) -> int:
    """이번 달(KST 기준) provider의 API 호출 건수."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT COUNT(*) FROM api_costs
               WHERE strftime('%Y-%m', recorded_at, '+9 hours') =
                     strftime('%Y-%m', 'now', '+9 hours')
                 AND provider = ?""",
            (provider,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
```

- [ ] **Step 4: `get_cost_widget` 컨텍스트 확장**

Edit `routers/settings.py::get_cost_widget` (현재 약 line 15):

```python
@router.get("/cost")
async def get_cost_widget(request: Request):
    from services.storage import get_monthly_cost, get_monthly_call_count
    claude_cost = await get_monthly_cost(config.DB_PATH, "claude")
    gpt_cost = await get_monthly_cost(config.DB_PATH, "gpt")
    claude_cli_count = await get_monthly_call_count(config.DB_PATH, "claude-cli")
    codex_cli_count = await get_monthly_call_count(config.DB_PATH, "codex-cli")
    return templates.TemplateResponse(
        request, "partials/api_cost.html",
        {
            "claude_cost": claude_cost,
            "claude_limit": config.CLAUDE_MONTHLY_LIMIT_USD,
            "gpt_cost": gpt_cost,
            "gpt_limit": config.GPT_MONTHLY_LIMIT_USD,
            "claude_cli_count": claude_cli_count,
            "codex_cli_count": codex_cli_count,
        },
    )
```

- [ ] **Step 5: `templates/partials/api_cost.html` — CLI 두 줄 추가**

`{% endfor %}` (line ~32) 바로 뒤, `<div class="pt-2 border-t border-[#E2E8E4]...">` 시작 전에 삽입:

```html
  <div class="space-y-1 mb-2 pt-2 border-t border-[#E2E8E4] dark:border-gray-700">
    {% for name, count, color in [
      ("Claude CLI", claude_cli_count, "#3B82F6"),
      ("Codex CLI",  codex_cli_count,  "#F97316")
    ] %}
    <div class="flex justify-between items-center text-[11px]">
      <div class="flex items-center gap-1.5">
        <span class="w-2 h-2 rounded-full" style="background:{{ color }}"></span>
        <span class="font-semibold text-[#1F2937] dark:text-gray-200">{{ name }}</span>
        <span class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A]">구독</span>
      </div>
      <span class="text-[12px] font-bold text-[#1F2937] dark:text-gray-200">{{ count }}회</span>
    </div>
    {% endfor %}
  </div>
```

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add services/storage.py routers/settings.py templates/partials/api_cost.html tests/test_routes_partials.py
git commit -m "feat: sidebar shows Claude CLI / Codex CLI monthly call counts"
```

---

## Task 11: usage 페이지 — 누적 카드 4개 + 차트 4스택

**Files:**
- Modify: `routers/settings.py::usage_report`
- Modify: `templates/usage.html`
- Test: `tests/test_routes_partials.py` (확장)

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_routes_partials.py`:

```python
@pytest.mark.asyncio
async def test_usage_report_renders_four_provider_stacks():
    """/api/settings/usage가 4 provider 색상 모두 마크업에 포함."""
    async def fake_monthly_cost(db, provider): return 0.0
    async def fake_count(db, provider): return 5
    async def fake_rows(db, limit=100): return []
    async def fake_daily(db, days=30):
        return [{"date": "2026-06-01",
                 "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    async def fake_month(db, months=12):
        return [{"month": "2026-06",
                 "claude": 0.0, "gpt": 0.0,
                 "claude_cli": 0.0, "codex_cli": 0.0, "total": 0.0}]
    with patch("services.storage.get_monthly_cost", new=fake_monthly_cost), \
         patch("services.storage.get_monthly_call_count", new=fake_count), \
         patch("services.storage.list_recent_api_costs", new=fake_rows), \
         patch("services.storage.aggregate_daily_costs", new=fake_daily), \
         patch("services.storage.aggregate_monthly_costs", new=fake_month):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/usage")
    assert resp.status_code == 200
    # 4 색상 모두 포함
    assert "#8B5CF6" in resp.text  # claude
    assert "#22C55E" in resp.text  # gpt
    assert "#3B82F6" in resp.text  # claude-cli
    assert "#F97316" in resp.text  # codex-cli
    # 라벨
    assert "Claude CLI" in resp.text
    assert "Codex CLI" in resp.text
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_routes_partials.py::test_usage_report_renders_four_provider_stacks -v`
Expected: FAIL (#3B82F6, "Claude CLI" 미존재)

- [ ] **Step 3: `usage_report` 컨텍스트 확장**

Edit `routers/settings.py::usage_report`:

```python
@router.get("/usage")
async def usage_report(request: Request):
    from services.storage import (
        get_monthly_cost, list_recent_api_costs,
        aggregate_daily_costs, aggregate_monthly_costs,
        get_monthly_call_count,
    )
    claude_cost = await get_monthly_cost(config.DB_PATH, "claude")
    gpt_cost = await get_monthly_cost(config.DB_PATH, "gpt")
    claude_cli_count = await get_monthly_call_count(config.DB_PATH, "claude-cli")
    codex_cli_count = await get_monthly_call_count(config.DB_PATH, "codex-cli")
    rows = await list_recent_api_costs(config.DB_PATH, limit=100)
    for r in rows:
        raw = r.get("recorded_at")
        if raw:
            try:
                dt = datetime.fromisoformat(raw).replace(tzinfo=UTC)
                r["recorded_at_kst"] = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                r["recorded_at_kst"] = raw
        else:
            r["recorded_at_kst"] = ""
    daily = await aggregate_daily_costs(config.DB_PATH, days=30)
    monthly = await aggregate_monthly_costs(config.DB_PATH, months=12)
    daily_max = max((d["total"] for d in daily), default=0.0)
    monthly_max = max((m["total"] for m in monthly), default=0.0)
    return templates.TemplateResponse(
        request, "usage.html",
        {
            "claude_cost": claude_cost,
            "claude_limit": config.CLAUDE_MONTHLY_LIMIT_USD,
            "gpt_cost": gpt_cost,
            "gpt_limit": config.GPT_MONTHLY_LIMIT_USD,
            "claude_cli_count": claude_cli_count,
            "codex_cli_count": codex_cli_count,
            "rows": rows,
            "daily": daily,
            "monthly": monthly,
            "daily_max": daily_max,
            "monthly_max": monthly_max,
        },
    )
```

- [ ] **Step 4: `templates/usage.html` — 누적 카드 4개 + 차트 4스택**

A. 누적 카드 섹션 (현재 2 카드 grid) 아래에 CLI 카드 그리드 추가. 기존 `<section class="grid grid-cols-1 md:grid-cols-2 gap-3">...</section>` 다음에 삽입:

```html
  <!-- CLI 누적 (구독, 비용 0) -->
  <section class="grid grid-cols-1 md:grid-cols-2 gap-3">
    {% for name, count, color in [
      ("Claude CLI", claude_cli_count, "#3B82F6"),
      ("Codex CLI",  codex_cli_count,  "#F97316")
    ] %}
    <div class="border border-[#E2E8E4] dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="w-3 h-3 rounded-full" style="background:{{ color }}"></span>
          <span class="text-sm font-semibold dark:text-gray-100">{{ name }}</span>
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A]">구독</span>
        </div>
        <div>
          <span class="text-base font-bold dark:text-gray-100">{{ count }}회</span>
          <span class="text-xs text-gray-400">/ 이번 달</span>
        </div>
      </div>
    </div>
    {% endfor %}
  </section>
```

B. 일별 차트의 각 day bar를 4 스택으로 교체. `{% for d in daily %}` 블록 안의 stack 부분을 다음으로:

```html
        {% for d in daily %}
        {% set claude_h = (d.claude / (daily_max or 1) * 100) | round(2) %}
        {% set gpt_h = (d.gpt / (daily_max or 1) * 100) | round(2) %}
        {% set claude_cli_h = (d.claude_cli / (daily_max or 1) * 100) | round(2) %}
        {% set codex_cli_h = (d.codex_cli / (daily_max or 1) * 100) | round(2) %}
        <div class="flex-1 flex flex-col-reverse min-w-[6px] rounded-t overflow-hidden bg-gray-100 dark:bg-gray-700/40 group relative"
             title="{{ d.date }} · Claude ${{ '%.4f'|format(d.claude) }} · GPT ${{ '%.4f'|format(d.gpt) }} · Claude CLI ${{ '%.4f'|format(d.claude_cli) }} · Codex CLI ${{ '%.4f'|format(d.codex_cli) }} · 합계 ${{ '%.4f'|format(d.total) }}">
          {% if d.claude > 0 %}<div style="height: {{ claude_h }}%; background: #8B5CF6;"></div>{% endif %}
          {% if d.gpt > 0 %}<div style="height: {{ gpt_h }}%; background: #22C55E;"></div>{% endif %}
          {% if d.claude_cli > 0 %}<div style="height: {{ claude_cli_h }}%; background: #3B82F6;"></div>{% endif %}
          {% if d.codex_cli > 0 %}<div style="height: {{ codex_cli_h }}%; background: #F97316;"></div>{% endif %}
        </div>
        {% endfor %}
```

C. 월별 차트도 동일하게 4 스택:

```html
        {% for m in monthly %}
        {% set claude_h = (m.claude / (monthly_max or 1) * 100) | round(2) %}
        {% set gpt_h = (m.gpt / (monthly_max or 1) * 100) | round(2) %}
        {% set claude_cli_h = (m.claude_cli / (monthly_max or 1) * 100) | round(2) %}
        {% set codex_cli_h = (m.codex_cli / (monthly_max or 1) * 100) | round(2) %}
        <div class="flex-1 flex flex-col items-center">
          <div class="w-full flex-1 flex flex-col-reverse rounded-t overflow-hidden bg-gray-100 dark:bg-gray-700/40"
               title="{{ m.month }} · Claude ${{ '%.4f'|format(m.claude) }} · GPT ${{ '%.4f'|format(m.gpt) }} · Claude CLI ${{ '%.4f'|format(m.claude_cli) }} · Codex CLI ${{ '%.4f'|format(m.codex_cli) }} · 합계 ${{ '%.4f'|format(m.total) }}">
            {% if m.claude > 0 %}<div style="height: {{ claude_h }}%; background: #8B5CF6;"></div>{% endif %}
            {% if m.gpt > 0 %}<div style="height: {{ gpt_h }}%; background: #22C55E;"></div>{% endif %}
            {% if m.claude_cli > 0 %}<div style="height: {{ claude_cli_h }}%; background: #3B82F6;"></div>{% endif %}
            {% if m.codex_cli > 0 %}<div style="height: {{ codex_cli_h }}%; background: #F97316;"></div>{% endif %}
          </div>
          <span class="text-[9px] text-gray-400 mt-1 font-mono">{{ m.month[-2:] }}</span>
        </div>
        {% endfor %}
```

D. 범례 4개로 확장. 기존 `<div class="flex items-center gap-4 text-[11px]...">` 블록을 교체:

```html
  <div class="flex items-center gap-4 text-[11px] text-gray-600 dark:text-gray-300 flex-wrap">
    <div class="flex items-center gap-1"><span class="w-3 h-3 rounded" style="background:#8B5CF6"></span> Claude API</div>
    <div class="flex items-center gap-1"><span class="w-3 h-3 rounded" style="background:#22C55E"></span> GPT API</div>
    <div class="flex items-center gap-1"><span class="w-3 h-3 rounded" style="background:#3B82F6"></span> Claude CLI</div>
    <div class="flex items-center gap-1"><span class="w-3 h-3 rounded" style="background:#F97316"></span> Codex CLI</div>
  </div>
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_routes_partials.py -v`
Expected: PASS

Run: `python -m pytest -q`
Expected: 약 183 passed

- [ ] **Step 6: 커밋**

```bash
git add routers/settings.py templates/usage.html tests/test_routes_partials.py
git commit -m "feat: usage page 4-stack charts + CLI summary cards"
```

---

## Task 12: `.env.example` + 회귀 검증 + 머지

**Files:**
- Modify: `.env.example` (없으면 생성)
- 머지: master로 fast-forward

- [ ] **Step 1: `.env.example` 확인 후 환경변수 추가**

Run: `cat .env.example 2>/dev/null || echo "없음"`

존재하면 다음 5줄을 끝에 append. 없으면 새로 생성하되 기존 `.env`를 참조하여 키만 비워서 작성:

```text
# agent-runner-bridge (Claude Code CLI / Codex CLI gateway)
BRIDGE_BASE_URL=http://127.0.0.1:8787
BRIDGE_TOKEN=
BRIDGE_CWD=/workspace/liby-runs
BRIDGE_TIMEOUT_SEC=900
DEFAULT_AI_PROVIDER=claude-cli
```

- [ ] **Step 2: 전체 회귀 테스트**

Run: `python -m pytest -q`
Expected: 약 183 passed (160 baseline + ~23 new)

- [ ] **Step 3: 수동 검증 가이드**

다음을 README나 별도 docs에 추가하지 않음 — 직접 사용자가 수동 검증.
필수 사전 조건:
1. `cd C:\path\to\agent-runner-bridge && docker compose up -d`
2. `creds/claude/.credentials.json`, `creds/codex/auth.json` 있는지 확인 (없으면 `pwsh ./scripts/sync-creds.ps1`)
3. `curl http://127.0.0.1:8787/health` → `{"ok":true}`
4. liby `.env`에 `BRIDGE_TOKEN=<bridge .env와 동일한 값>` 설정
5. liby 서버 재기동 (ffmpeg PATH 포함)
6. 짧은 YouTube 영상으로 분석 — provider는 default `claude-cli`
7. 사이드바 위젯에 "Claude CLI · 1회" 표시 확인
8. `/api/settings/usage` 새 탭에서 4 누적 카드 + 차트 4 스택 + 범례 확인
9. bridge 컨테이너 정지 후 같은 분석 시도 → task failed + 명확한 에러 메시지 확인
10. provider 드롭다운에서 "Claude API ($)"로 변경 후 재시도 → 정상 동작 확인

- [ ] **Step 4: 커밋**

```bash
git add .env.example
git commit -m "docs: bridge env vars in .env.example"
```

- [ ] **Step 5: master로 fast-forward 머지**

```bash
git checkout master
git merge --ff-only feature/cli-first-bridge-2026-06-02
git log --oneline -10
```

Expected: 직전 master HEAD 위로 약 9개 새 커밋.

- [ ] **Step 6: 최종 회귀**

Run: `python -m pytest -q`
Expected: 약 183 passed

---

## 자체 검토 (Self-Review)

### Spec coverage

| Spec 요구 | Task |
|---|---|
| `bridge_client.py` (httpx, 폴링, 에러 매핑) | Task 3 |
| `bridge.py` (`BridgeProvider(adapter)`) | Task 4 |
| `chunking.py` 공유 헬퍼 | Task 2 |
| `config.py` BRIDGE_* | Task 3 (Step 4) |
| `services/ai/__init__.py` 라우팅 | Task 5 |
| `services/storage.py::aggregate_*` 4 provider | Task 6 |
| 5 input 폼 provider 옵션 추가 | Task 8 |
| 사이드바 위젯 CLI 두 줄 | Task 10 |
| `templates/usage.html` 4스택 차트 | Task 11 |
| `DEFAULT_AI_PROVIDER` 기본값 변경 | Task 9 |
| `.env.example` 환경변수 | Task 12 |
| 비용 0 처리 | Task 4 Step 7 (`cost_usd=run.usage.total_cost_usd`) |
| 에러 시나리오 (token, 401, 402, polling timeout, failed) | Task 3 Step 8 |
| JSON 파싱 실패 | Task 4 Step 11/13 (chapters / translate 케이스 처리) |
| 모든 LLM 호출 위임 (summarize/run_tier3/chapters/translate) | Task 4 |
| 테스트 +15 | Tasks 2,3,4,5,6,7,8,10,11에 분산. 합계: 3+6+10+5+2+1+1+1+1 = 약 30건 (목표 초과, 안전 마진) |
| 수동 검증 절차 | Task 12 Step 3 |

빠진 항목 없음.

### 타입 일관성

- `BridgeUsage.input_tokens`(int) / `BridgeUsage.total_cost_usd`(float) — `services/storage.py::record_api_cost(input_tokens: int, output_tokens: int, cost_usd: float)` 시그니처와 매칭
- `BridgeProvider.name()` → `"claude-cli"` / `"codex-cli"` — Task 4와 Task 5 모두 일관
- `get_provider("claude-cli")` → `BridgeProvider("claude")` — `name() == "claude-cli"`. 라우팅(Task 5)과 BridgeProvider(Task 4)에서 동일.
- `chunking.build_paragraphs(data) -> list[dict]` — `_build_paragraphs`와 동일 시그니처 (re-export). Task 2와 Task 4가 모두 동일 이름 사용.
- `aggregate_daily_costs`/`aggregate_monthly_costs` 결과 dict 키: `claude`, `gpt`, `claude_cli`, `codex_cli`, `total` — Task 6/11 일관 (`d.claude_cli`).

### Placeholder 스캔

- 모든 step에 실제 코드 블록 또는 정확한 명령어. "TODO"/"TBD"/"비슷하게" 없음. ✅
