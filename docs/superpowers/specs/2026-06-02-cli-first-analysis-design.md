# CLI-first 분석 파이프라인 (Claude Code CLI / Codex CLI 우선)

**작성일**: 2026-06-02
**상태**: design

## 배경 / 목표

liby의 모든 LLM 호출은 현재 Anthropic / OpenAI API를 직접 호출한다. 사용자는 이미 Claude Pro · ChatGPT Plus 구독 중이므로, 같은 호출을 **구독으로 인증된 로컬 CLI**(Claude Code, Codex)로 흘리면 추가 비용 없이 분석을 돌릴 수 있다.

`C:\path\to\agent-runner-bridge`에 이미 다음을 갖춘 Docker 게이트웨이가 셋업되어 있다.

- `POST /v1/runs` REST + SSE 이벤트 스트림
- `AUTH_PREFERENCE=local`: 구독 인증(`~/.claude/.credentials.json`, `~/.codex/auth.json`)을 우선 사용, 없을 때만 API 키 폴백
- Bearer 토큰 인증, 워크스페이스 allowlist, 월별 예산 가드
- 응답: `summary`(CLI의 최종 메시지), `sessionId`, `usage`(토큰), `exitCode`

liby가 이 bridge를 한 통로로 두고 모든 LLM 호출을 보내면 API 비용은 사실상 0으로 떨어진다.

**목표**: provider `claude-cli`, `codex-cli`를 liby의 1순위 분석 엔진으로 추가하고, 기본값을 `claude-cli`로 둔다. API provider(`claude`, `gpt`)는 명시 선택 시에만 사용한다.

## 비목표

- 자동 폴백 체인 (사용자가 명시적으로 재시도)
- bridge 헬스 체크 대시보드
- 멀티-턴 대화(세션 재사용은 follow-up)
- 구독 만료 시 자동 API 전환
- bridge 자체에 코드를 추가하는 것 — liby는 bridge를 client로만 사용

## 핵심 결정 (brainstorming 결과)

| 결정 | 선택 | 근거 |
|---|---|---|
| Transport | agent-runner-bridge HTTP | 이미 구현·검증된 게이트웨이. 인증/예산/SSE 무료 |
| Provider 선택 UI | 수동 선택 유지, default=`claude-cli` | 사용자 통제 보존. 의도치 않은 API 호출 방지 |
| 위임 범위 | 모든 LLM 호출 (요약, 청킹 partial, 챕터 생성, 챕터 번역) | API 비용 0에 가장 근접 |
| Usage 추적 | `api_costs.provider`에 `claude-cli`/`codex-cli` 추가, 보통 `cost_usd=0` | "절약량" 한눈 + 토큰 추적 유지 |
| 실패 처리 | 에러로 task failed, 사용자가 provider 변경해 재시도 | 자동 폴백은 구독 절약 의도와 충돌 |

## 아키텍처

```
[liby FastAPI :8000]                       [agent-runner-bridge :8787 Docker]
   │                                          │
   │ get_provider("claude-cli")               │
   ▼                                          │
 BridgeProvider(adapter="claude")             │
   │ summarize(text, ...)                     │
   ├──► chunking.py: _chunk_for_llm           │
   │   각 chunk마다:                          │
   │     bridge_client.run(                   │
   │       prompt, adapter="claude",          │
   │       cwd=BRIDGE_CWD)                    │
   │            POST /v1/runs ────────────────►  spawn `claude --print
   │            (Bearer token)                   --output-format stream-json`
   │            GET /v1/runs/<id> 폴링       ◄──  결과 JSONL
   │   <- summary 텍스트                       │
   ├── _extract_json(summary) -> dict          │
   ├── _merge_partials                         │
   ▼                                           │
 SummaryResult                                 │
   │                                           │
   ▼                                           │
 record_api_cost(provider="claude-cli",        │
   tokens=usage, cost_usd=usage.totalCostUsd or 0)
```

## 파일 변경

### 신규

#### `services/ai/bridge_client.py`
httpx 기반 bridge 클라이언트.

**Public 함수**:
- `async def run_agent(prompt: str, *, adapter: str, cwd: str | None = None, model: str | None = None, timeout_sec: int = 900) -> BridgeRunResult`
  - `BRIDGE_BASE_URL`로 `POST /v1/runs` Bearer 인증
  - 받은 `runId`로 `GET /v1/runs/<id>` 1~2초 간격 폴링 until `status in {succeeded, failed, cancelled, timed_out}`
  - `succeeded` → `BridgeRunResult(summary, session_id, usage)` 반환
  - 그 외 terminal → `BridgeError(status, exit_code, summary)` raise

**Dataclasses**:
```python
@dataclass
class BridgeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0

@dataclass
class BridgeRunResult:
    summary: str
    session_id: str | None
    usage: BridgeUsage
```

**에러**:
```python
class BridgeError(RuntimeError):
    def __init__(self, status: str, exit_code: int | None, summary: str): ...
```

#### `services/ai/bridge.py`
`BridgeProvider(adapter: str)` — `AIProvider` 구현.

- 생성자에서 `adapter ∈ {"claude", "codex"}` 검증, `config.BRIDGE_TOKEN` 미설정이면 즉시 `RuntimeError`
- `name() -> str`: `"claude-cli"` 또는 `"codex-cli"`
- `summarize(text, source_type, mode, existing_topics)`:
  - `chunking.should_chunk(text)` 분기. 단일 호출 / map-reduce 두 경로
  - 각 LLM 호출은 `bridge_client.run_agent(prompt, adapter=self.adapter)`
  - 응답 `summary` 문자열에서 첫 `{`~마지막 `}` 슬라이스 → `json.loads`
  - 실패 시 `BridgeError` 또는 `ValueError("JSON 파싱 실패")` → 라우터에서 task failed 처리
  - `cost_usd = run_result.usage.total_cost_usd` (구독 모드면 0), `models_used=[self.adapter]`
- `run_tier3`, `generate_chapters`, `translate_chapters`: 각각 기존 `ClaudeProvider`의 프롬프트를 그대로 가져와 transport만 bridge_client로

#### `services/ai/chunking.py`
`claude.py`에서 transport-무관 로직 분리. import 시 양 provider가 공유.

- `should_chunk(text: str) -> bool` (현재 `CHUNK_THRESHOLD = 18000`)
- `chunk_for_llm(text: str) -> list[ChunkRef]` (현재 `_chunk_for_llm`)
- `chunk_range_hint(chunk: ChunkRef) -> str` (현재 `_chunk_range_hint`)
- `merge_partials(partials: list[dict]) -> dict` (현재 `_merge_partials` + section 정렬·재번호 포함)
- `extract_json(text: str) -> dict` (현재 `_extract_json`)
- `SUMMARY_MERGE_PROMPT` 상수
- `build_paragraphs(data: dict) -> list[dict]` (현재 `_build_paragraphs`)

#### `tests/test_bridge_client.py`
- 성공: POST 202 + 폴링 succeeded → `BridgeRunResult` 반환
- 실패: 폴링 failed → `BridgeError` raise (exit_code, summary 포함)
- 타임아웃: 폴링 timed_out → `BridgeError`
- Bearer 헤더 검증
- httpx mock (respx 또는 httpx.MockTransport)

#### `tests/test_bridge_provider.py`
- summarize 단일(청킹 미발생) — bridge_client.run_agent mock
- summarize 청킹 — 호출 횟수 = chunk_count + 1(merge) 검증
- generate_chapters — bridge_client.run_agent 호출 1회, 결과 파싱
- JSON 파싱 실패 → `ValueError`
- `BRIDGE_TOKEN` 미설정 시 `__init__` raise
- `name()` 검증

### 수정

#### `config.py`
```python
BRIDGE_BASE_URL: str = os.getenv("BRIDGE_BASE_URL", "http://127.0.0.1:8787")
BRIDGE_TOKEN: str = os.getenv("BRIDGE_TOKEN", "")
BRIDGE_CWD: str = os.getenv("BRIDGE_CWD", "/workspace/liby-runs")
BRIDGE_TIMEOUT_SEC: int = int(os.getenv("BRIDGE_TIMEOUT_SEC", "900"))
DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "claude-cli")
```

#### `services/ai/__init__.py`
```python
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
    return FallbackProvider()  # bridge 없는 환경용 단순 subprocess 폴백(기존 동작 유지). 신규 호출은 claude-cli/codex-cli 권장
```

#### `services/ai/claude.py`
- 청킹 관련 private 함수들 (`_chunk_for_llm`, `_chunk_range_hint`, `_merge_partials`, `_extract_json`, `_build_paragraphs`, `SUMMARY_MERGE_PROMPT`)을 `chunking.py`에서 re-export 또는 import해서 사용
- 다른 외부 사용처(`from services.ai.claude import _build_paragraphs`)는 import 경로만 `chunking`으로 변경
- 청킹 임계값/프롬프트 동작은 동일하게 유지 (테스트 회귀 0)

#### `services/storage.py`
- `aggregate_daily_costs`, `aggregate_monthly_costs`의 GROUP BY에 `claude-cli`, `codex-cli` 추가 → 결과 dict에 4개 키 (`claude`, `gpt`, `claude_cli`, `codex_cli`, `total`)
- `record_api_cost` 시그니처는 변경 없음 (provider 문자열만 새 값 받음)

#### 라우터 5개 (`youtube.py`, `pdf.py`, `text.py`, `code.py`, `markdown.py`)
- `provider: str = Form(config.DEFAULT_AI_PROVIDER)` 그대로 유지
- 새 값을 거부하지 않도록 별도 화이트리스트 검증이 없는지 확인. 있으면 추가

#### 템플릿
**분석 폼들** (현재 위치 확인 후 일괄):
```html
<select name="provider">
  <option value="claude-cli">Claude Code CLI (구독, 무료)</option>
  <option value="codex-cli">Codex CLI (구독, 무료)</option>
  <option value="claude">Claude API ($)</option>
  <option value="gpt">GPT API ($)</option>
</select>
```

**`templates/usage.html`**:
- 누적 카드: 2 → 4개 (`claude`, `gpt`, `claude-cli`, `codex-cli`). CLI 두 개는 한도가 없으므로 progress bar 대신 "이번 달 호출 N회 · 토큰 X" 표시
- 일별/월별 차트: 4-stack stacked bar. 색상:
  - claude: `#8B5CF6` (보라)
  - gpt: `#22C55E` (초록)
  - claude-cli: `#3B82F6` (하늘)
  - codex-cli: `#F97316` (주황)
- 범례 4개

**`templates/partials/api_cost.html`** (사이드바 위젯):
- API 두 개는 기존 progress bar 유지
- CLI 두 개는 한 줄 요약 ("Claude CLI · 12회 · 45.2K tok", "Codex CLI · 3회 · 8.1K tok")

### 환경변수 / 운영

`.env.example` 추가:
```
BRIDGE_BASE_URL=http://127.0.0.1:8787
BRIDGE_TOKEN=
BRIDGE_CWD=/workspace/liby-runs
BRIDGE_TIMEOUT_SEC=900
DEFAULT_AI_PROVIDER=claude-cli
```

bridge가 `http://127.0.0.1:8787`에서 듣고 있어야 함. bridge가 죽어 있으면 `claude-cli` 호출이 즉시 connection refused로 실패 → 사용자에게 명확한 에러 메시지.

## 데이터 흐름 (예: YouTube 53분 영상 분석)

1. 사용자 폼 제출 (`provider=claude-cli` 기본). `routers/youtube.py::analyze_youtube`가 task 생성
2. 백그라운드 task가 `get_provider("claude-cli")` → `BridgeProvider(adapter="claude")`
3. transcript ≥18,000자 → `chunking.chunk_for_llm` 분할 (예: 4개 chunk)
4. 각 chunk마다 `bridge_client.run_agent(chunk_prompt, adapter="claude")`:
   - `POST http://127.0.0.1:8787/v1/runs` with `{"adapter":"claude","prompt":...,"cwd":"/workspace/liby-runs"}`
   - bridge가 컨테이너 안에서 `claude --print --output-format stream-json` spawn (구독 인증 사용)
   - 1.5초마다 `GET /v1/runs/<runId>` 폴링
   - `status=succeeded` → response.summary 반환
5. 4개 partial JSON → `chunking.merge_partials` → 통합 결과
6. `record_api_cost(provider="claude-cli", input_tokens=Σ, output_tokens=Σ, cost_usd=0.0, item_id=item.id, model="claude-sonnet-4-6")`
7. task 완료 → `noteCompleted` 이벤트 → 사이드바 위젯 + usage 페이지 즉시 갱신

## 에러 / 실패 시나리오

| 시나리오 | 처리 |
|---|---|
| `BRIDGE_TOKEN` 미설정 | `BridgeProvider.__init__`에서 즉시 `RuntimeError("BRIDGE_TOKEN 미설정")` |
| bridge 서버 미응답 (connection refused) | `httpx.ConnectError` → `BridgeError("bridge 연결 실패: <message>")` |
| bridge 401 Unauthorized | `BridgeError("bridge 인증 실패: 토큰 확인")` |
| bridge 402 budget_exceeded | `BridgeError("bridge 월 예산 초과")` 사용자 메시지로 안내 |
| 폴링 timed_out / failed / cancelled | `BridgeError(status, exit_code, summary)` |
| CLI 응답에서 JSON 추출 실패 | `ValueError("LLM 응답 JSON 파싱 실패: <앞 200자>")` |

모든 에러는 라우터 `try/except`에서 잡아서 task `failed`로 마무리, 모달의 에러 메시지 영역에 표시. 사용자는 분석 폼에서 provider를 `claude`(API)로 바꿔 재시도.

## 테스트

신규/수정 테스트 (실제 bridge·CLI 호출 없이 mock만):

- `tests/test_bridge_client.py` (~6 케이스)
- `tests/test_bridge_provider.py` (~5 케이스)
- `tests/test_get_provider.py` (또는 기존 `test_fallback_provider.py` 확장) — `claude-cli`/`codex-cli` 라우팅 검증
- `tests/test_storage.py` — `aggregate_*`가 4 provider 키 채우는지
- `tests/test_routes_partials.py` — usage 페이지에 4 provider markup, 사이드바 widget에 CLI 라인 노출
- `tests/test_claude_provider.py` — chunking 이동 후 회귀 없음 확인

목표: 현재 160 → 약 175 (+15) 모두 통과.

## 검증 (수동)

1. bridge 컨테이너 띄움 (`cd C:\path\to\agent-runner-bridge && docker compose up -d`)
2. `.env`에 `BRIDGE_TOKEN`, `DEFAULT_AI_PROVIDER=claude-cli` 설정 후 liby 재기동
3. 짧은 YouTube 영상 분석 → 사이드바 위젯에 "Claude CLI · 1회" 증가, usage 페이지 차트에 하늘색 막대 출현
4. 53분 영상 분석 → 청킹 4회 + merge 1회 모두 bridge 경유, cost 0 유지
5. bridge 컨테이너 멈춤 → 같은 영상 분석 시 즉시 task failed, 에러 메시지 "bridge 연결 실패" 확인
6. provider를 `Claude API`로 바꿔 재시도 → 정상 동작

## 분량 / 사이즈

- 신규 3 파일 (`bridge_client.py`, `bridge.py`, `chunking.py`)
- 수정 ~10 파일 (config, ai/__init__, claude.py, storage.py, 5 라우터, usage.html, api_cost.html)
- 테스트 추가 ~15건
- Subagent-Driven Development로 진행 적합 (3~5 task로 분해 가능)
