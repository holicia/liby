# liby Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YouTube·PDF·Markdown·Code 입력을 AI로 자동 요약하고, 제텔카스텐 방식으로 노트를 관리하는 개인용 웹 애플리케이션 구축

**Architecture:** FastAPI 백엔드가 Jinja2+HTMX 프론트엔드에 HTML 조각을 서빙한다. AI 분석은 Claude/GPT 3단계 파이프라인(추출→요약→인사이트)으로 처리하며, API 한도 초과 시 Claude Code CLI → Codex CLI 순으로 폴백한다. 결과는 SQLite + Markdown 파일 이중 저장한다.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, Tailwind CSS (CDN), SQLite (aiosqlite), anthropic SDK, openai SDK, youtube-transcript-api, PyMuPDF

---

## 파일 구조

```
liby/
├── main.py                          # FastAPI 앱, 라우터 등록
├── config.py                        # 환경변수, API Key, 모델 설정
├── models.py                        # SQLite 스키마 + DB 초기화
├── routers/
│   ├── __init__.py
│   ├── youtube.py                   # POST /api/youtube
│   ├── pdf.py                       # POST /api/pdf
│   ├── items.py                     # GET/DELETE /api/items, POST /api/items/{id}/upgrade
│   └── settings.py                  # GET/PUT /api/settings (API 한도)
├── services/
│   ├── __init__.py
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── base.py                  # AIProvider 추상 클래스 + SummaryResult
│   │   ├── claude.py                # ClaudeProvider (Haiku→Sonnet→Opus)
│   │   ├── openai_provider.py       # OpenAIProvider (mini→4o→o1-mini)
│   │   └── fallback.py              # CLI 폴백 (Claude Code, Codex)
│   ├── extractor.py                 # YouTube 자막 추출, PDF 텍스트 추출, 청크 분할
│   └── storage.py                   # DB 저장, .md 파일 생성
├── templates/
│   ├── base.html                    # 공통 레이아웃 (네비바, 사이드바, HTMX/Tailwind CDN)
│   ├── index.html                   # 홈 (최근 업데이트 + 오늘의 추천)
│   └── partials/
│       ├── input_youtube.html       # YouTube URL 입력 패널
│       ├── input_pdf.html           # PDF 업로드 패널
│       ├── input_markdown.html      # Markdown 입력 패널
│       ├── input_code.html          # Code 입력 패널
│       ├── note_card.html           # 노트 카드 (목록용)
│       ├── note_list.html           # 노트 목록 (HTMX 갱신 대상)
│       ├── note_detail.html         # 노트 전체 보기
│       ├── sidebar_topics.html      # 주제 목록 (HTMX 갱신 대상)
│       ├── api_cost.html            # Claude/GPT 비용 위젯
│       └── topic_confirm.html       # 새 주제 확인 팝업
├── static/                          # (빈 폴더 — Tailwind/HTMX는 CDN)
├── vault/
│   ├── youtube/
│   ├── pdf/
│   ├── markdown/
│   └── code/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # pytest fixtures (DB, 클라이언트)
│   ├── test_models.py
│   ├── test_extractor.py
│   ├── test_ai_base.py
│   ├── test_claude_provider.py
│   ├── test_openai_provider.py
│   ├── test_storage.py
│   ├── test_routes_youtube.py
│   ├── test_routes_pdf.py
│   └── test_routes_items.py
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Task 1: 프로젝트 셋업

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `config.py`
- Create: `main.py`

- [ ] **Step 1: requirements.txt 작성**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
jinja2==3.1.4
python-multipart==0.0.9
aiosqlite==0.20.0
anthropic==0.34.0
openai==1.45.0
youtube-transcript-api==0.6.2
PyMuPDF==1.24.9
python-dotenv==1.0.1
httpx==0.27.0
pytest==8.3.0
pytest-asyncio==0.24.0
pytest-mock==3.14.0
```

- [ ] **Step 2: 의존성 설치**

```bash
pip install -r requirements.txt
```

- [ ] **Step 3: .env.example 작성**

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
CLAUDE_MONTHLY_LIMIT_USD=2.00
GPT_MONTHLY_LIMIT_USD=2.00
DEFAULT_AI_PROVIDER=claude
VAULT_PATH=./vault
DB_PATH=./liby.db
```

- [ ] **Step 4: .gitignore 작성**

```
.env
liby.db
vault/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.superpowers/
```

- [ ] **Step 5: config.py 작성**

```python
import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_MONTHLY_LIMIT_USD = float(os.getenv("CLAUDE_MONTHLY_LIMIT_USD", "2.00"))
GPT_MONTHLY_LIMIT_USD = float(os.getenv("GPT_MONTHLY_LIMIT_USD", "2.00"))
DEFAULT_AI_PROVIDER = os.getenv("DEFAULT_AI_PROVIDER", "claude")
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
DB_PATH = os.getenv("DB_PATH", "./liby.db")

CLAUDE_MODELS = {
    "tier1": "claude-haiku-4-5",
    "tier2": "claude-sonnet-4-6",
    "tier3": "claude-opus-4-7",
}
GPT_MODELS = {
    "tier1": "gpt-4o-mini",
    "tier2": "gpt-4o",
    "tier3": "o1-mini",
}
```

- [ ] **Step 6: vault 디렉토리 생성**

```bash
mkdir -p vault/youtube vault/pdf vault/markdown vault/code
mkdir -p routers services/ai templates/partials tests static
touch routers/__init__.py services/__init__.py services/ai/__init__.py tests/__init__.py
```

- [ ] **Step 7: main.py 작성 (골격)**

```python
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="liby")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

- [ ] **Step 8: 서버 기동 확인**

```bash
uvicorn main:app --reload
```

브라우저에서 http://localhost:8000 접속 → 500이 아닌 응답(빈 템플릿 오류)이 나오면 OK

- [ ] **Step 9: 커밋**

```bash
git init
git add requirements.txt .env.example .gitignore config.py main.py
git commit -m "chore: initial project setup"
```

---

## Task 2: 데이터베이스 스키마

**Files:**
- Create: `models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_models.py`:
```python
import pytest
import aiosqlite
from models import init_db, get_db

@pytest.mark.asyncio
async def test_init_db_creates_items_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
        )
        row = await cursor.fetchone()
    assert row is not None

@pytest.mark.asyncio
async def test_init_db_creates_settings_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        )
        row = await cursor.fetchone()
    assert row is not None
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: models.py 작성**

```python
import aiosqlite
import config

CREATE_ITEMS = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    summary TEXT,
    key_points TEXT,
    sections TEXT,
    tags TEXT,
    topic TEXT,
    summary_mode TEXT DEFAULT 'quick',
    main_arguments TEXT,
    insights TEXT,
    questions_raised TEXT,
    zettel_links TEXT,
    related_concepts TEXT,
    ai_provider TEXT,
    ai_models TEXT,
    api_cost_usd REAL DEFAULT 0.0,
    md_file_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

CREATE_API_COSTS = """
CREATE TABLE IF NOT EXISTS api_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    item_id INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

async def init_db(db_path: str = config.DB_PATH):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_ITEMS)
        await db.execute(CREATE_SETTINGS)
        await db.execute(CREATE_API_COSTS)
        await db.commit()

async def get_db(db_path: str = config.DB_PATH):
    return aiosqlite.connect(db_path)
```

- [ ] **Step 4: conftest.py 작성**

`tests/conftest.py`:
```python
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from models import init_db

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_models.py -v
```

Expected: 2 passed

- [ ] **Step 6: main.py에 DB 초기화 추가**

```python
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from models import init_db
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="liby", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

- [ ] **Step 7: 커밋**

```bash
git add models.py tests/conftest.py tests/test_models.py main.py
git commit -m "feat: SQLite schema with items, settings, api_costs tables"
```

---

## Task 3: SummaryResult + AIProvider 추상 클래스

**Files:**
- Create: `services/ai/base.py`
- Create: `tests/test_ai_base.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_ai_base.py`:
```python
from services.ai.base import SummaryResult, AIProvider

def test_summary_result_quick_defaults():
    r = SummaryResult(
        title="Test",
        language="ko",
        word_count=100,
        reading_time_min=1,
        sections=[],
        summary="요약입니다.",
        key_points=["포인트1"],
        tags=["AI"],
        suggested_topic="AI/ML",
        summary_mode="quick",
    )
    assert r.main_arguments is None
    assert r.insights is None
    assert r.summary_mode == "quick"

def test_summary_result_cost_usd_default():
    r = SummaryResult(
        title="T", language="en", word_count=0, reading_time_min=0,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
    )
    assert r.cost_usd == 0.0

def test_ai_provider_is_abstract():
    import inspect
    assert inspect.isabstract(AIProvider)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_ai_base.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: base.py 작성**

`services/ai/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SummaryResult:
    title: str
    language: str
    word_count: int
    reading_time_min: int
    sections: list[str]
    summary: str
    key_points: list[str]
    tags: list[str]
    suggested_topic: str
    summary_mode: str  # "quick" | "detailed"
    main_arguments: Optional[list[str]] = None
    insights: Optional[list[str]] = None
    questions_raised: Optional[list[str]] = None
    zettel_links: Optional[list[int]] = None
    related_concepts: Optional[list[str]] = None
    cost_usd: float = 0.0
    models_used: list[str] = field(default_factory=list)

class AIProvider(ABC):
    @abstractmethod
    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult: ...

    @abstractmethod
    async def run_tier3(self, summary: str) -> SummaryResult: ...

    @abstractmethod
    def name(self) -> str: ...
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_ai_base.py -v
```

Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add services/ai/base.py tests/test_ai_base.py
git commit -m "feat: SummaryResult dataclass and AIProvider abstract base"
```

---

## Task 4: ClaudeProvider

**Files:**
- Create: `services/ai/claude.py`
- Create: `tests/test_claude_provider.py`

- [ ] **Step 1: 테스트 작성 (mock 사용)**

`tests/test_claude_provider.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.ai.claude import ClaudeProvider

SAMPLE_TEXT = "LLM은 대규모 언어 모델이다. " * 20

@pytest.fixture
def provider():
    return ClaudeProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_summarize_quick_returns_summary_result(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{
  "title": "LLM 개요",
  "language": "ko",
  "word_count": 100,
  "reading_time_min": 1,
  "sections": [],
  "summary": "LLM은 대규모 언어 모델이다.",
  "key_points": ["핵심1", "핵심2"],
  "tags": ["AI", "LLM"],
  "suggested_topic": "AI/ML"
}
""")]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

    with patch.object(provider._client.messages, "create", return_value=mock_response):
        result = await provider.summarize(SAMPLE_TEXT, "youtube", "quick", ["AI/ML"])

    assert result.title == "LLM 개요"
    assert result.summary_mode == "quick"
    assert result.main_arguments is None
    assert result.cost_usd > 0

@pytest.mark.asyncio
async def test_summarize_quick_mode_skips_tier3(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="""
{
  "title": "T", "language": "ko", "word_count": 10,
  "reading_time_min": 1, "sections": [],
  "summary": "요약", "key_points": ["p1"],
  "tags": ["tag"], "suggested_topic": "주제"
}
""")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=10)

    with patch.object(provider._client.messages, "create", return_value=mock_response) as mock_create:
        result = await provider.summarize(SAMPLE_TEXT, "pdf", "quick", [])

    # quick 모드에서는 Tier2까지만 → create 호출 1회 (Tier1+2 통합)
    assert mock_create.call_count == 1
    assert result.main_arguments is None

def test_provider_name(provider):
    assert provider.name() == "claude"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_claude_provider.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.ai.claude'`

- [ ] **Step 3: claude.py 작성**

`services/ai/claude.py`:
```python
import json
import anthropic
from services.ai.base import AIProvider, SummaryResult
import config

TIER1_PROMPT = """다음 텍스트에서 핵심 문장을 추출하고 구조를 파악하세요.
소스 타입: {source_type}

텍스트:
{text}

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자,
  "reading_time_min": 숫자, "sections": ["섹션1", ...]}}"""

TIER2_PROMPT = """다음 내용을 분석하여 노트를 작성하세요.
기존 주제 목록: {existing_topics}

내용:
{text}

JSON으로 응답하세요:
{{"title": "제목", "language": "ko|en", "word_count": 숫자,
  "reading_time_min": 숫자, "sections": [],
  "summary": "5~10문장 요약",
  "key_points": ["핵심1", "핵심2", "핵심3"],
  "tags": ["태그1", "태그2"],
  "suggested_topic": "기존_주제_중_하나_또는_새_주제명"}}"""

TIER3_PROMPT = """다음 요약을 바탕으로 심층 분석을 수행하세요.

요약: {summary}

JSON으로 응답하세요:
{{"main_arguments": ["논거1", "논거2"],
  "insights": ["인사이트1", "인사이트2"],
  "questions_raised": ["질문1", "질문2"],
  "related_concepts": ["개념1", "개념2"]}}"""

CLAUDE_PRICING = {
    "claude-haiku-4-5":   {"input": 0.25,  "output": 1.25},
    "claude-sonnet-4-6":  {"input": 3.0,   "output": 15.0},
    "claude-opus-4-7":    {"input": 15.0,  "output": 75.0},
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = CLAUDE_PRICING.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str = config.ANTHROPIC_API_KEY):
        self._client = anthropic.Anthropic(api_key=api_key)

    def name(self) -> str:
        return "claude"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used = []

        # Tier 1+2 통합 (단일 호출로 비용 절감)
        model = config.CLAUDE_MODELS["tier2"]
        prompt = TIER2_PROMPT.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = self._client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
        total_cost += _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        models_used.append(model)

        data = json.loads(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=data.get("sections", []),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._run_tier3(result, total_cost, models_used)

        return result

    async def run_tier3(self, summary: str) -> SummaryResult:
        empty = SummaryResult(
            title="", language="ko", word_count=0, reading_time_min=0,
            sections=[], summary=summary, key_points=[], tags=[],
            suggested_topic="", summary_mode="detailed",
        )
        return await self._run_tier3(empty, 0.0, [])

    async def _run_tier3(
        self,
        result: SummaryResult,
        total_cost: float,
        models_used: list[str],
    ) -> SummaryResult:
        model = config.CLAUDE_MODELS["tier3"]
        prompt = TIER3_PROMPT.format(summary=result.summary)
        resp = self._client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(resp.content[0].text)
        total_cost += _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        models_used.append(model)

        result.main_arguments = data.get("main_arguments", [])
        result.insights = data.get("insights", [])
        result.questions_raised = data.get("questions_raised", [])
        result.related_concepts = data.get("related_concepts", [])
        result.cost_usd = total_cost
        result.models_used = models_used
        return result
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_claude_provider.py -v
```

Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add services/ai/claude.py tests/test_claude_provider.py
git commit -m "feat: ClaudeProvider with Tier2+3 pipeline"
```

---

## Task 5: OpenAIProvider

**Files:**
- Create: `services/ai/openai_provider.py`
- Create: `tests/test_openai_provider.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_openai_provider.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from services.ai.openai_provider import OpenAIProvider

SAMPLE_TEXT = "GPT는 생성형 AI 모델이다. " * 20

@pytest.fixture
def provider():
    return OpenAIProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_summarize_quick_returns_result(provider):
    mock_choice = MagicMock()
    mock_choice.message.content = """
{
  "title": "GPT 개요", "language": "ko", "word_count": 50,
  "reading_time_min": 1, "sections": [],
  "summary": "GPT는 생성형 AI이다.",
  "key_points": ["포인트1"],
  "tags": ["AI"],
  "suggested_topic": "AI/ML"
}
"""
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    mock_resp.model = "gpt-4o"

    with patch.object(provider._client.chat.completions, "create", return_value=mock_resp):
        result = await provider.summarize(SAMPLE_TEXT, "pdf", "quick", [])

    assert result.title == "GPT 개요"
    assert result.summary_mode == "quick"
    assert result.cost_usd > 0

def test_provider_name(provider):
    assert provider.name() == "gpt"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_openai_provider.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: openai_provider.py 작성**

`services/ai/openai_provider.py`:
```python
import json
from openai import OpenAI
from services.ai.base import AIProvider, SummaryResult
from services.ai.claude import TIER2_PROMPT, TIER3_PROMPT
import config

GPT_PRICING = {
    "gpt-4o-mini": {"input": 0.15,  "output": 0.60},
    "gpt-4o":      {"input": 2.50,  "output": 10.0},
    "o1-mini":     {"input": 3.0,   "output": 12.0},
}

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = GPT_PRICING.get(model, {"input": 2.50, "output": 10.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000

class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str = config.OPENAI_API_KEY):
        self._client = OpenAI(api_key=api_key)

    def name(self) -> str:
        return "gpt"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        total_cost = 0.0
        models_used = []
        model = config.GPT_MODELS["tier2"]

        prompt = TIER2_PROMPT.format(
            text=text[:12000],
            existing_topics=", ".join(existing_topics) or "없음",
        )
        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        total_cost += _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        models_used.append(model)

        data = json.loads(raw)
        result = SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=data.get("sections", []),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=total_cost,
            models_used=models_used,
        )

        if mode == "detailed":
            result = await self._gpt_tier3(result, total_cost, models_used)

        return result

    async def _gpt_tier3(self, result: SummaryResult, total_cost: float, models_used: list[str]) -> SummaryResult:
        tier3_model = config.GPT_MODELS["tier3"]
        t3_prompt = TIER3_PROMPT.format(summary=result.summary)
        t3_resp = self._client.chat.completions.create(
            model=tier3_model,
            messages=[{"role": "user", "content": t3_prompt}],
            response_format={"type": "json_object"},
        )
        t3_data = json.loads(t3_resp.choices[0].message.content)
        total_cost += _calc_cost(tier3_model, t3_resp.usage.prompt_tokens, t3_resp.usage.completion_tokens)
        models_used.append(tier3_model)
        result.main_arguments = t3_data.get("main_arguments", [])
        result.insights = t3_data.get("insights", [])
        result.questions_raised = t3_data.get("questions_raised", [])
        result.related_concepts = t3_data.get("related_concepts", [])
        result.cost_usd = total_cost
        result.models_used = models_used
        return result

    async def run_tier3(self, summary: str) -> SummaryResult:
        empty = SummaryResult(
            title="", language="ko", word_count=0, reading_time_min=0,
            sections=[], summary=summary, key_points=[], tags=[],
            suggested_topic="", summary_mode="detailed",
        )
        return await self._gpt_tier3(empty, 0.0, [])
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_openai_provider.py -v
```

Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add services/ai/openai_provider.py tests/test_openai_provider.py
git commit -m "feat: OpenAIProvider with Tier2+3 pipeline"
```

---

## Task 6: Fallback Provider (Claude Code CLI → Codex CLI)

**Files:**
- Create: `services/ai/fallback.py`

- [ ] **Step 1: fallback.py 작성**

`services/ai/fallback.py`:
```python
import subprocess
import shutil
import json
from services.ai.base import AIProvider, SummaryResult

FALLBACK_PROMPT = """다음 내용을 분석하여 JSON으로 응답하세요.

내용:
{text}

JSON 형식:
{{"title": "제목", "language": "ko", "word_count": 숫자,
  "reading_time_min": 숫자, "sections": [],
  "summary": "5~10문장 요약",
  "key_points": ["핵심1", "핵심2"],
  "tags": ["태그1"],
  "suggested_topic": "주제명"}}"""

def _detect_cli() -> tuple[str, str] | tuple[None, None]:
    if shutil.which("claude"):
        return "claude", "claude"
    if shutil.which("codex"):
        return "codex", "codex"
    return None, None

def _run_cli(cli: str, prompt: str) -> str:
    result = subprocess.run(
        [cli, prompt],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"{cli} CLI 오류: {result.stderr}")
    return result.stdout.strip()

class FallbackProvider(AIProvider):
    def __init__(self):
        self._cli_name, self._cli_cmd = _detect_cli()

    def is_available(self) -> bool:
        return self._cli_name is not None

    def name(self) -> str:
        return self._cli_name or "fallback"

    async def summarize(
        self,
        text: str,
        source_type: str,
        mode: str,
        existing_topics: list[str],
    ) -> SummaryResult:
        if not self.is_available():
            raise RuntimeError("CLI 폴백 없음: claude, codex 중 하나를 설치하세요.")
        prompt = FALLBACK_PROMPT.format(text=text[:8000])
        raw = _run_cli(self._cli_cmd, prompt)
        # JSON 추출 (CLI 출력에 다른 텍스트가 섞일 수 있음)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        return SummaryResult(
            title=data.get("title", "제목 없음"),
            language=data.get("language", "ko"),
            word_count=data.get("word_count", 0),
            reading_time_min=data.get("reading_time_min", 0),
            sections=data.get("sections", []),
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            tags=data.get("tags", []),
            suggested_topic=data.get("suggested_topic", ""),
            summary_mode=mode,
            cost_usd=0.0,
            models_used=[self._cli_name],
        )
```

- [ ] **Step 2: 폴백 선택 함수 작성 (services/ai/__init__.py)**

`services/ai/__init__.py`:
```python
import config
from services.ai.claude import ClaudeProvider
from services.ai.openai_provider import OpenAIProvider
from services.ai.fallback import FallbackProvider
from services.ai.base import AIProvider

def get_provider(name: str | None = None) -> AIProvider:
    provider_name = name or config.DEFAULT_AI_PROVIDER
    if provider_name == "claude":
        return ClaudeProvider()
    if provider_name == "gpt":
        return OpenAIProvider()
    return FallbackProvider()
```

- [ ] **Step 3: 커밋**

```bash
git add services/ai/fallback.py services/ai/__init__.py
git commit -m "feat: CLI fallback provider (Claude Code -> Codex)"
```

---

## Task 7: 텍스트 추출 서비스

**Files:**
- Create: `services/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_extractor.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from services.extractor import extract_youtube, extract_pdf, chunk_text

def test_chunk_text_splits_long_text():
    text = "단어 " * 5000
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1100 for c in chunks)

def test_chunk_text_short_text_returns_one_chunk():
    text = "짧은 텍스트"
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) == 1

@pytest.mark.asyncio
async def test_extract_youtube_returns_text_and_video_id():
    mock_transcript = [{"text": "안녕하세요", "start": 0.0}, {"text": "반갑습니다", "start": 2.0}]
    with patch("services.extractor.YouTubeTranscriptApi.get_transcript", return_value=mock_transcript):
        text, video_id = await extract_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert "안녕하세요" in text
    assert video_id == "dQw4w9WgXcQ"

@pytest.mark.asyncio
async def test_extract_pdf_returns_text(tmp_path):
    # 실제 PDF 없이 mock 처리
    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.get_text.return_value = "PDF 내용입니다."
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=False)

    with patch("services.extractor.fitz.open", return_value=mock_doc):
        text = await extract_pdf("/fake/path.pdf")
    assert "PDF 내용" in text
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_extractor.py -v
```

Expected: FAIL

- [ ] **Step 3: extractor.py 작성**

`services/extractor.py`:
```python
import re
import fitz
from youtube_transcript_api import YouTubeTranscriptApi

def _extract_video_id(url: str) -> str:
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"YouTube ID를 추출할 수 없습니다: {url}")

def chunk_text(text: str, max_chars: int = 10000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    for p in paragraphs:
        if len(current) + len(p) > max_chars:
            if current:
                chunks.append(current.strip())
            current = p
        else:
            current += "\n\n" + p
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text[:max_chars]]

async def extract_youtube(url: str) -> tuple[str, str]:
    video_id = _extract_video_id(url)
    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko", "en"])
    text = " ".join(t["text"] for t in transcript)
    return text, video_id

async def extract_pdf(file_path: str) -> str:
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_extractor.py -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add services/extractor.py tests/test_extractor.py
git commit -m "feat: YouTube/PDF text extractor with chunk splitting"
```

---

## Task 8: Storage 서비스

**Files:**
- Create: `services/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_storage.py`:
```python
import pytest
import json
import aiosqlite
from services.storage import save_note, get_note, record_api_cost, get_monthly_cost
from services.ai.base import SummaryResult
from models import init_db

@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path

def make_result(mode="quick") -> SummaryResult:
    return SummaryResult(
        title="테스트 노트", language="ko", word_count=100,
        reading_time_min=1, sections=[],
        summary="요약입니다.", key_points=["핵심1"],
        tags=["AI"], suggested_topic="AI/ML",
        summary_mode=mode, cost_usd=0.003,
        models_used=["claude-sonnet-4-6"],
    )

@pytest.mark.asyncio
async def test_save_and_get_note(db, tmp_path):
    result = make_result()
    note_id = await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="https://youtube.com/watch?v=abc",
        result=result, ai_provider="claude",
    )
    assert note_id > 0

    note = await get_note(db, note_id)
    assert note["title"] == "테스트 노트"
    assert json.loads(note["tags"]) == ["AI"]

@pytest.mark.asyncio
async def test_save_note_creates_md_file(db, tmp_path):
    vault = tmp_path / "vault" / "youtube"
    vault.mkdir(parents=True)
    result = make_result()
    await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="https://youtube.com/watch?v=abc",
        result=result, ai_provider="claude",
    )
    md_files = list(vault.glob("*.md"))
    assert len(md_files) == 1

@pytest.mark.asyncio
async def test_record_and_get_monthly_cost(db):
    await record_api_cost(db, provider="claude", model="claude-sonnet-4-6",
                          input_tokens=1000, output_tokens=500, cost_usd=0.01)
    cost = await get_monthly_cost(db, provider="claude")
    assert cost == pytest.approx(0.01)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_storage.py -v
```

Expected: FAIL

- [ ] **Step 3: storage.py 작성**

`services/storage.py`:
```python
import json
import os
from datetime import datetime
import aiosqlite
from services.ai.base import SummaryResult

def _make_md_content(
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "{result.title}"',
        f"type: {source_type}",
        f"source: {source_url}",
        f"tags: {json.dumps(result.tags, ensure_ascii=False)}",
        f"topic: {result.suggested_topic}",
        f"ai_provider: {ai_provider}",
        f"summary_mode: {result.summary_mode}",
        f"created: {today}",
        "---",
        "",
        "## 요약",
        result.summary,
        "",
        "## 핵심 포인트",
    ]
    for p in result.key_points:
        lines.append(f"- {p}")
    if result.main_arguments:
        lines += ["", "## 핵심 논거"]
        for a in result.main_arguments:
            lines.append(f"- {a}")
    if result.insights:
        lines += ["", "## 인사이트"]
        for i in result.insights:
            lines.append(f"- {i}")
    if result.questions_raised:
        lines += ["", "## 탐구할 질문"]
        for q in result.questions_raised:
            lines.append(f"- {q}")
    return "\n".join(lines)

async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    safe_title = result.title[:40].replace(" ", "-").replace("/", "-")
    filename = f"{today}-{safe_title}.md"
    subdir = os.path.join(vault_path, source_type)
    os.makedirs(subdir, exist_ok=True)
    md_path = os.path.join(subdir, filename)

    md_content = _make_md_content(source_type, source_url, result, ai_provider)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, main_arguments, insights, questions_raised,
                related_concepts, ai_provider, ai_models, api_cost_usd, md_file_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, result.title, source_url, result.summary,
                json.dumps(result.key_points, ensure_ascii=False),
                json.dumps(result.sections, ensure_ascii=False),
                json.dumps(result.tags, ensure_ascii=False),
                result.suggested_topic, result.summary_mode,
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                ai_provider,
                json.dumps(result.models_used, ensure_ascii=False),
                result.cost_usd, md_path,
            )
        )
        await db.commit()
        return cursor.lastrowid

async def get_note(db_path: str, note_id: int) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM items WHERE id = ?", (note_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def record_api_cost(
    db_path: str, provider: str, model: str,
    input_tokens: int, output_tokens: int, cost_usd: float,
    item_id: int | None = None,
):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO api_costs (provider, model, input_tokens, output_tokens, cost_usd, item_id)
               VALUES (?,?,?,?,?,?)""",
            (provider, model, input_tokens, output_tokens, cost_usd, item_id),
        )
        await db.commit()

async def get_monthly_cost(db_path: str, provider: str) -> float:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs
               WHERE provider = ?
               AND strftime('%Y-%m', recorded_at) = strftime('%Y-%m', 'now')""",
            (provider,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_storage.py -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: storage service — SQLite save and markdown file export"
```

---

## Task 9: YouTube 라우터

**Files:**
- Create: `routers/youtube.py`
- Create: `tests/test_routes_youtube.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_routes_youtube.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult

MOCK_RESULT = SummaryResult(
    title="테스트 영상", language="ko", word_count=200,
    reading_time_min=2, sections=[],
    summary="요약 내용입니다.", key_points=["핵심1"],
    tags=["AI"], suggested_topic="AI/ML",
    summary_mode="quick", cost_usd=0.002,
    models_used=["claude-sonnet-4-6"],
)

@pytest.mark.asyncio
async def test_analyze_youtube_returns_htmx_fragment():
    with patch("routers.youtube.extract_youtube", return_value=("자막 텍스트", "abc123")), \
         patch("routers.youtube.get_provider") as mock_get, \
         patch("routers.youtube.save_note", return_value=1), \
         patch("routers.youtube.record_api_cost"):
        mock_provider = AsyncMock()
        mock_provider.name.return_value = "claude"
        mock_provider.summarize = AsyncMock(return_value=MOCK_RESULT)
        mock_get.return_value = mock_provider

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/youtube", data={
                "url": "https://youtube.com/watch?v=abc123",
                "provider": "claude",
                "mode": "quick",
            })
    assert resp.status_code == 200
    assert "테스트 영상" in resp.text

@pytest.mark.asyncio
async def test_analyze_youtube_missing_url_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/youtube", data={"provider": "claude", "mode": "quick"})
    assert resp.status_code == 422
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_routes_youtube.py -v
```

Expected: FAIL

- [ ] **Step 3: routers/youtube.py 작성**

`routers/youtube.py`:
```python
from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
import config
from services.extractor import extract_youtube
from services.ai import get_provider
from services.storage import save_note, record_api_cost

router = APIRouter(prefix="/api/youtube", tags=["youtube"])
templates = Jinja2Templates(directory="templates")

@router.post("")
async def analyze_youtube(
    request: Request,
    url: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
):
    text, video_id = await extract_youtube(url)
    ai = get_provider(provider)

    async with get_db_topics() as topics:
        result = await ai.summarize(text, "youtube", mode, topics)

    note_id = await save_note(
        db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
        source_type="youtube", source_url=url,
        result=result, ai_provider=ai.name(),
    )
    await record_api_cost(
        config.DB_PATH, ai.name(),
        model=result.models_used[-1] if result.models_used else "",
        input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
        item_id=note_id,
    )
    return templates.TemplateResponse(
        "partials/note_card.html",
        {"request": request, "note": _result_to_dict(note_id, result, "youtube", url)},
    )

def _result_to_dict(note_id, result, source_type, source_url):
    return {
        "id": note_id, "type": source_type, "source_url": source_url,
        "title": result.title, "summary": result.summary,
        "key_points": result.key_points, "tags": result.tags,
        "topic": result.suggested_topic, "summary_mode": result.summary_mode,
        "ai_provider": "claude", "cost_usd": result.cost_usd,
        "created_at": "방금 전",
    }

from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_topics():
    import aiosqlite
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT topic FROM items WHERE topic IS NOT NULL")
        rows = await cursor.fetchall()
    yield [r[0] for r in rows]
```

- [ ] **Step 4: main.py에 라우터 등록**

```python
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from models import init_db
from contextlib import asynccontextmanager
from routers import youtube, pdf, items, settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="liby", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_routes_youtube.py -v
```

Expected: 2 passed

- [ ] **Step 6: 커밋**

```bash
git add routers/youtube.py main.py tests/test_routes_youtube.py
git commit -m "feat: YouTube analysis endpoint with HTMX response"
```

---

## Task 10: PDF 라우터

**Files:**
- Create: `routers/pdf.py`
- Create: `tests/test_routes_pdf.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_routes_pdf.py`:
```python
import pytest
import io
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from main import app
from services.ai.base import SummaryResult

MOCK_RESULT = SummaryResult(
    title="테스트 PDF", language="ko", word_count=500,
    reading_time_min=3, sections=[],
    summary="PDF 요약입니다.", key_points=["핵심1"],
    tags=["논문"], suggested_topic="논문",
    summary_mode="quick", cost_usd=0.005,
    models_used=["claude-sonnet-4-6"],
)

@pytest.mark.asyncio
async def test_analyze_pdf_returns_note_card():
    pdf_bytes = b"%PDF-1.4 fake content"
    with patch("routers.pdf.extract_pdf", return_value="PDF 텍스트"), \
         patch("routers.pdf.get_provider") as mock_get, \
         patch("routers.pdf.save_note", return_value=2), \
         patch("routers.pdf.record_api_cost"):
        mock_provider = AsyncMock()
        mock_provider.name.return_value = "claude"
        mock_provider.summarize = AsyncMock(return_value=MOCK_RESULT)
        mock_get.return_value = mock_provider

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/pdf",
                data={"provider": "claude", "mode": "quick"},
                files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            )
    assert resp.status_code == 200
    assert "테스트 PDF" in resp.text
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_routes_pdf.py -v
```

Expected: FAIL

- [ ] **Step 3: routers/pdf.py 작성**

`routers/pdf.py`:
```python
import os
import tempfile
from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
import config
from services.extractor import extract_pdf
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from routers.youtube import get_db_topics, _result_to_dict

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
templates = Jinja2Templates(directory="templates")

@router.post("")
async def analyze_pdf(
    request: Request,
    file: UploadFile = File(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        text = await extract_pdf(tmp_path)
        ai = get_provider(provider)
        async with get_db_topics() as topics:
            result = await ai.summarize(text, "pdf", mode, topics)

        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="pdf", source_url=file.filename or "unknown.pdf",
            result=result, ai_provider=ai.name(),
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        return templates.TemplateResponse(
            "partials/note_card.html",
            {"request": request, "note": _result_to_dict(note_id, result, "pdf", file.filename)},
        )
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_routes_pdf.py -v
```

Expected: 1 passed

- [ ] **Step 5: 커밋**

```bash
git add routers/pdf.py tests/test_routes_pdf.py
git commit -m "feat: PDF upload and analysis endpoint"
```

---

## Task 11: Items 라우터 (목록·검색·업그레이드)

**Files:**
- Create: `routers/items.py`
- Create: `routers/settings.py`
- Create: `tests/test_routes_items.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_routes_items.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from main import app

MOCK_NOTE = {
    "id": 1, "type": "youtube", "title": "테스트", "summary": "요약",
    "tags": '["AI"]', "topic": "AI/ML", "summary_mode": "quick",
    "key_points": '["핵심1"]', "ai_provider": "claude",
    "cost_usd": 0.003, "created_at": "2026-05-23",
    "source_url": "https://youtube.com/watch?v=abc",
}

@pytest.mark.asyncio
async def test_get_items_returns_list():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/items")
    assert resp.status_code == 200
    assert "테스트" in resp.text

@pytest.mark.asyncio
async def test_get_items_with_tag_filter():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/items?tags=AI&tags=LLM")
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_upgrade_to_detailed():
    from services.ai.base import SummaryResult
    detailed_result = SummaryResult(
        title="테스트", language="ko", word_count=100,
        reading_time_min=1, sections=[],
        summary="요약", key_points=["핵심1"],
        tags=["AI"], suggested_topic="AI/ML",
        summary_mode="detailed", cost_usd=0.01,
        models_used=["claude-opus-4-7"],
        main_arguments=["논거1"],
        insights=["인사이트1"],
        questions_raised=["질문1"],
        related_concepts=["개념1"],
    )
    with patch("routers.items.get_note", return_value=MOCK_NOTE), \
         patch("routers.items.get_provider") as mock_get, \
         patch("routers.items.upgrade_to_detailed", return_value=detailed_result), \
         patch("routers.items.record_api_cost"):
        mock_get.return_value = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/items/1/upgrade")
    assert resp.status_code == 200
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_routes_items.py -v
```

Expected: FAIL

- [ ] **Step 3: storage.py에 list_notes, upgrade_to_detailed 추가**

`services/storage.py` 하단에 추가:
```python
async def list_notes(
    db_path: str,
    topic: str | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[dict]:
    query = "SELECT * FROM items WHERE 1=1"
    params = []
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if search:
        query += " AND (title LIKE ? OR summary LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if tags:
        for tag in tags:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]

async def upgrade_to_detailed(
    db_path: str, note_id: int, result: "SummaryResult"
) -> "SummaryResult":
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE items SET
               summary_mode='detailed',
               main_arguments=?, insights=?, questions_raised=?,
               related_concepts=?, api_cost_usd=api_cost_usd+?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                result.cost_usd, note_id,
            )
        )
        await db.commit()
    return result

async def get_topics(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT topic, COUNT(*) as count FROM items WHERE topic IS NOT NULL GROUP BY topic ORDER BY count DESC"
        )
        rows = await cursor.fetchall()
    return [{"topic": r[0], "count": r[1]} for r in rows]

async def get_random_notes(db_path: str, n: int = 4) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM items ORDER BY RANDOM() LIMIT ?", (n,)
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: routers/items.py 작성**

`routers/items.py`:
```python
from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from typing import Optional
import config
from services.ai import get_provider
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes
)

router = APIRouter(prefix="/api/items", tags=["items"])
templates = Jinja2Templates(directory="templates")

@router.get("")
async def get_items(
    request: Request,
    topic: Optional[str] = Query(None),
    tags: list[str] = Query([]),
    search: Optional[str] = Query(None),
):
    notes = await list_notes(config.DB_PATH, topic=topic, tags=tags, search=search)
    return templates.TemplateResponse(
        "partials/note_list.html",
        {"request": request, "notes": notes},
    )

@router.get("/{note_id}")
async def get_item(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note:
        return templates.TemplateResponse("partials/note_card.html",
                                          {"request": request, "note": None})
    return templates.TemplateResponse(
        "partials/note_detail.html",
        {"request": request, "note": note},
    )

@router.post("/{note_id}/upgrade")
async def upgrade_note(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note:
        return {"error": "노트를 찾을 수 없습니다."}

    provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))
    detailed = await provider.run_tier3(note["summary"])
    await upgrade_to_detailed(config.DB_PATH, note_id, detailed)
    await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, detailed.cost_usd, note_id)

    updated_note = await get_note(config.DB_PATH, note_id)
    return templates.TemplateResponse(
        "partials/note_card.html",
        {"request": request, "note": updated_note},
    )
```

- [ ] **Step 5: routers/settings.py 작성**

`routers/settings.py`:
```python
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
import aiosqlite, config

router = APIRouter(prefix="/api/settings", tags=["settings"])
templates = Jinja2Templates(directory="templates")

@router.get("/cost")
async def get_cost_widget(request: Request):
    from services.storage import get_monthly_cost
    claude_cost = await get_monthly_cost(config.DB_PATH, "claude")
    gpt_cost = await get_monthly_cost(config.DB_PATH, "gpt")
    return templates.TemplateResponse("partials/api_cost.html", {
        "request": request,
        "claude_cost": claude_cost,
        "claude_limit": config.CLAUDE_MONTHLY_LIMIT_USD,
        "gpt_cost": gpt_cost,
        "gpt_limit": config.GPT_MONTHLY_LIMIT_USD,
    })
```

- [ ] **Step 6: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_routes_items.py -v
```

Expected: 3 passed

- [ ] **Step 7: 커밋**

```bash
git add routers/items.py routers/settings.py services/storage.py tests/test_routes_items.py
git commit -m "feat: items CRUD, search/filter, quick->detailed upgrade endpoint"
```

---

## Task 12: HTML 템플릿 (base + index + partials)

**Files:**
- Create: `templates/base.html`
- Create: `templates/index.html`
- Create: `templates/partials/note_card.html`
- Create: `templates/partials/note_list.html`
- Create: `templates/partials/api_cost.html`
- Create: `templates/partials/input_youtube.html`
- Create: `templates/partials/input_pdf.html`

- [ ] **Step 1: base.html 작성**

`templates/base.html`:
```html
<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}liby{% endblock %}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<style>
  :root { --green:#1F6F4A; --sage:#A8CBB2; --sage-light:#EAF4EE; --border:#E2E8E4; --sub:#F3F5F4; }
  [data-theme="dark"] { --green:#34A66A; --sage:#2D6B4A; --sage-light:#14291E; --border:#2D3748; --sub:#1F2937; }
  body { background: white; }
  [data-theme="dark"] body { background: #111827; color: #F9FAFB; }
</style>
</head>
<body class="text-[#1F2937] dark:text-gray-100">

<!-- NAVBAR -->
<nav class="sticky top-0 z-10 bg-white border-b border-[#E2E8E4] flex items-stretch h-12 px-5 shadow-sm dark:bg-gray-900 dark:border-gray-700">
  <span class="font-extrabold text-[17px] text-[#1F6F4A] flex items-center pr-5 border-r border-[#E2E8E4] mr-2">📚 liby</span>
  <div class="flex items-stretch">
    {% for tab in [("YouTube","youtube"),("PDF","pdf"),("Markdown","markdown"),("Code","code")] %}
    <button
      class="px-4 text-xs font-medium text-gray-400 border-b-2 border-transparent hover:text-gray-700 transition-colors"
      hx-get="/partials/input/{{ tab[1] }}"
      hx-target="#input-panel"
      hx-swap="innerHTML"
      onclick="setActiveTab(this)"
    >{{ tab[0] }}</button>
    {% endfor %}
  </div>
  <div class="ml-auto flex items-center">
    <button onclick="toggleTheme()" class="text-xs px-3 py-1 border border-[#E2E8E4] rounded-md text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors" id="theme-btn">다크 모드</button>
  </div>
</nav>

<!-- INPUT PANEL -->
<div id="input-panel" class="bg-[#EAF4EE] border-b border-[#E2E8E4] px-5 py-3 dark:bg-[#14291E] dark:border-gray-700">
  {% include "partials/input_youtube.html" %}
</div>

<!-- LAYOUT -->
<div class="flex" style="height: calc(100vh - 96px);">

  <!-- SIDEBAR -->
  <aside class="w-52 border-r border-[#E2E8E4] bg-white flex flex-col dark:bg-gray-900 dark:border-gray-700">
    <div class="flex-1 overflow-y-auto p-3 space-y-0.5">
      <a href="/"
         class="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#EAF4EE] text-[#1F6F4A] font-semibold text-xs cursor-pointer">
        <span class="w-2 h-2 rounded-full bg-[#1F6F4A]"></span>전체 노트
        <span class="ml-auto bg-[#1F6F4A] text-white text-[10px] px-2 py-0.5 rounded-full font-bold" id="total-count">0</span>
      </a>

      <p class="text-[10px] font-bold uppercase tracking-widest text-gray-400 px-2 pt-3 pb-1">주제별</p>
      <div id="topic-list"
           hx-get="/api/items/topics"
           hx-trigger="load"
           hx-swap="innerHTML">
      </div>
      <button class="w-full text-center text-xs text-gray-400 border border-dashed border-[#E2E8E4] rounded-lg py-1.5 mt-1 hover:border-[#1F6F4A] hover:text-[#1F6F4A] transition-colors"
              onclick="promptNewTopic()">+ 새 주제 추가</button>

      <p class="text-[10px] font-bold uppercase tracking-widest text-gray-400 px-2 pt-4 pb-1">태그 검색</p>
      <input type="text" placeholder="태그 입력..."
             class="w-full text-xs bg-[#F3F5F4] border border-[#E2E8E4] rounded-lg px-3 py-2 text-gray-500 outline-none focus:border-[#1F6F4A] dark:bg-gray-800"
             onkeydown="addTagFilter(event, this)">
      <div id="tag-chips" class="flex flex-wrap gap-1 px-1 mt-1"></div>
    </div>

    <!-- API COST FOOTER -->
    <div id="api-cost-widget"
         hx-get="/api/settings/cost"
         hx-trigger="load, every 60s"
         hx-swap="innerHTML">
    </div>
  </aside>

  <!-- MAIN -->
  <main class="flex-1 overflow-y-auto px-6 py-5 bg-white dark:bg-gray-950">
    {% block content %}{% endblock %}
  </main>
</div>

<script>
function toggleTheme() {
  const html = document.documentElement;
  const btn = document.getElementById("theme-btn");
  html.setAttribute("data-theme", html.getAttribute("data-theme") === "light" ? "dark" : "light");
  btn.textContent = html.getAttribute("data-theme") === "dark" ? "라이트 모드" : "다크 모드";
}
function setActiveTab(el) {
  document.querySelectorAll("nav button").forEach(b => b.classList.remove("border-[#1F6F4A]", "text-[#1F6F4A]", "font-semibold"));
  el.classList.add("border-[#1F6F4A]", "text-[#1F6F4A]", "font-semibold");
}
let activeTags = [];
function addTagFilter(e, input) {
  if (e.key !== "Enter" || !input.value.trim()) return;
  const tag = input.value.trim();
  if (!activeTags.includes(tag)) {
    activeTags.push(tag);
    renderTagChips();
    refreshNotes();
  }
  input.value = "";
}
function removeTag(tag) {
  activeTags = activeTags.filter(t => t !== tag);
  renderTagChips();
  refreshNotes();
}
function renderTagChips() {
  const container = document.getElementById("tag-chips");
  container.innerHTML = activeTags.map(t =>
    `<span class="text-[10px] bg-[#EAF4EE] text-[#1F6F4A] px-2 py-0.5 rounded font-medium flex items-center gap-1">
      ${t} <span class="opacity-50 cursor-pointer" onclick="removeTag('${t}')">×</span>
    </span>`
  ).join("");
}
function refreshNotes() {
  const params = new URLSearchParams();
  activeTags.forEach(t => params.append("tags", t));
  htmx.ajax("GET", `/api/items?${params}`, { target: "#note-list", swap: "innerHTML" });
}
function promptNewTopic() {
  const name = prompt("새 주제 이름을 입력하세요:");
  if (name) refreshNotes();
}
</script>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: templates/index.html 작성**

`templates/index.html`:
```html
{% extends "base.html" %}
{% block content %}
<p class="text-[11px] font-bold uppercase tracking-widest text-gray-400 mb-3">최근 업데이트</p>
<div id="note-list"
     hx-get="/api/items"
     hx-trigger="load"
     hx-swap="innerHTML"
     class="space-y-2 mb-7">
</div>

<p class="text-[11px] font-bold uppercase tracking-widest text-gray-400 mb-3">오늘의 추천 노트</p>
<div id="recommended-notes"
     hx-get="/api/items/random"
     hx-trigger="load"
     hx-swap="innerHTML"
     class="grid grid-cols-2 gap-2">
</div>
{% endblock %}
```

- [ ] **Step 3: partials/note_card.html 작성**

`templates/partials/note_card.html`:
```html
{% if note %}
<div class="bg-[#F3F5F4] border border-[#E2E8E4] rounded-xl p-4 flex gap-3 items-start hover:border-[#A8CBB2] hover:shadow-sm transition-all cursor-pointer dark:bg-gray-800 dark:border-gray-700">
  <span class="flex-shrink-0 mt-0.5 bg-[#EAF4EE] text-[#1F6F4A] text-[10px] font-bold px-2 py-1 rounded border border-[#A8CBB2]">{{ note.type | upper }}</span>
  <div class="flex-1">
    <div class="font-semibold text-[13px] text-[#1F2937] mb-1 dark:text-gray-100">{{ note.title }}</div>
    <div class="text-[10px] text-gray-400 mb-2 flex items-center gap-2">
      {{ note.created_at }}
      · {{ note.ai_provider | capitalize }}
      <span class="text-[9px] font-bold px-1.5 py-0.5 rounded
        {% if note.summary_mode == 'detailed' %}bg-yellow-100 text-yellow-700{% else %}bg-blue-100 text-blue-700{% endif %}">
        {% if note.summary_mode == 'detailed' %}상세 정리{% else %}빠른 정리{% endif %}
      </span>
    </div>
    {% if note.summary %}
    <p class="text-xs text-gray-600 leading-relaxed mb-2 line-clamp-2 dark:text-gray-400">{{ note.summary }}</p>
    {% endif %}
    <div class="flex items-center gap-1.5 flex-wrap">
      {% if note.tags %}
        {% set tags = note.tags | tojson | fromjson if note.tags is string else note.tags %}
        {% for tag in tags[:3] %}
        <span class="text-[10px] bg-[#EAF4EE] text-[#1F6F4A] px-2 py-0.5 rounded font-medium">{{ tag }}</span>
        {% endfor %}
      {% endif %}
      {% if note.topic %}
      <span class="text-[10px] bg-[#EAF4EE] text-[#1F6F4A] border border-[#A8CBB2] px-2 py-0.5 rounded font-semibold">{{ note.topic }}</span>
      {% endif %}
      <span class="ml-auto text-[10px] text-gray-400">${{ "%.3f"|format(note.cost_usd or 0) }}</span>
    </div>
  </div>
  <div class="flex flex-col gap-1 flex-shrink-0">
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] hover:border-[#A8CBB2] transition-colors dark:bg-gray-700">전체 보기</button>
    {% if note.summary_mode == 'quick' %}
    <button class="text-[10px] bg-[#1F6F4A] text-white rounded px-2.5 py-1 font-semibold hover:opacity-90"
            hx-post="/api/items/{{ note.id }}/upgrade"
            hx-target="closest div.flex"
            hx-swap="outerHTML">상세 정리 →</button>
    {% else %}
    <button class="text-[10px] bg-white border border-[#E2E8E4] rounded px-2.5 py-1 text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] transition-colors dark:bg-gray-700">.md 열기</button>
    {% endif %}
  </div>
</div>
{% endif %}
```

- [ ] **Step 4: partials/note_list.html 작성**

`templates/partials/note_list.html`:
```html
{% if notes %}
  {% for note in notes %}
    {% include "partials/note_card.html" %}
  {% endfor %}
{% else %}
<p class="text-sm text-gray-400 py-8 text-center">노트가 없습니다. 위에서 YouTube URL이나 PDF를 분석해보세요.</p>
{% endif %}
```

- [ ] **Step 5: partials/input_youtube.html 작성**

`templates/partials/input_youtube.html`:
```html
<form hx-post="/api/youtube" hx-target="#note-list" hx-swap="afterbegin" class="flex gap-2 items-center">
  <input name="url" type="url" required
         placeholder="YouTube URL을 입력하세요 (예: https://youtube.com/watch?v=...)"
         class="flex-1 bg-white border border-[#E2E8E4] rounded-lg px-4 py-2.5 text-sm text-gray-700 outline-none focus:border-[#1F6F4A] dark:bg-gray-800 dark:text-gray-200">
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

- [ ] **Step 6: partials/input_pdf.html 작성**

`templates/partials/input_pdf.html`:
```html
<form hx-post="/api/pdf" hx-target="#note-list" hx-swap="afterbegin" hx-encoding="multipart/form-data" class="flex gap-2 items-center">
  <input name="file" type="file" accept=".pdf" required
         class="flex-1 bg-white border border-[#E2E8E4] rounded-lg px-3 py-2 text-xs text-gray-500 dark:bg-gray-800">
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

- [ ] **Step 7: partials/api_cost.html 작성**

`templates/partials/api_cost.html`:
```html
<div class="border-t border-[#E2E8E4] p-3 dark:border-gray-700">
  <div class="flex justify-between items-center mb-2">
    <span class="text-[10px] font-bold uppercase tracking-widest text-gray-400">이번 달 API</span>
    <span class="text-[10px] text-[#1F6F4A] cursor-pointer">상세 →</span>
  </div>

  {% for name, cost, limit, color in [
    ("Claude", claude_cost, claude_limit, "#8B5CF6"),
    ("GPT",    gpt_cost,   gpt_limit,    "#22C55E")
  ] %}
  {% set pct = [((cost / limit) * 100) | int, 100] | min %}
  {% set status = "초과" if pct >= 100 else ("임박" if pct >= 80 else "정상") %}
  <div class="mb-2">
    <div class="flex justify-between items-center mb-1">
      <div class="flex items-center gap-1.5">
        <span class="w-2 h-2 rounded-full" style="background:{{ color }}"></span>
        <span class="text-[11px] font-semibold text-[#1F2937] dark:text-gray-200">{{ name }}</span>
        <span class="text-[9px] font-bold px-1.5 py-0.5 rounded
          {% if status == '정상' %}bg-[#EAF4EE] text-[#1F6F4A]
          {% elif status == '임박' %}bg-yellow-100 text-yellow-700
          {% else %}bg-red-100 text-red-600{% endif %}">{{ status }}</span>
      </div>
      <div>
        <span class="text-[12px] font-bold text-[#1F2937] dark:text-gray-200">${{ "%.2f"|format(cost) }}</span>
        <span class="text-[10px] text-gray-400"> / ${{ "%.2f"|format(limit) }}</span>
      </div>
    </div>
    <div class="bg-[#E2E8E4] rounded h-1 overflow-hidden dark:bg-gray-700">
      <div class="h-full rounded" style="width:{{ pct }}%; background:{{ color }}; opacity:.75;"></div>
    </div>
  </div>
  {% endfor %}

  <div class="pt-2 border-t border-[#E2E8E4] space-y-1 dark:border-gray-700">
    {% for num, label, active in [(1,"Anthropic / OpenAI API",True),(2,"Claude Code CLI",False),(3,"Codex CLI",False)] %}
    <div class="flex items-center gap-1.5 text-[10px] text-gray-400">
      <span class="w-3.5 h-3.5 rounded-full border flex items-center justify-center text-[8px] font-bold
        {% if active %}bg-[#1F6F4A] text-white border-[#1F6F4A]{% else %}border-gray-300 text-gray-400{% endif %}">{{ num }}</span>
      <span class="{% if active %}text-[#1F6F4A] font-semibold{% endif %}">{{ label }}</span>
    </div>
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 8: main.py에 partials 라우터 추가**

`main.py` 하단에 추가:
```python
from fastapi.responses import HTMLResponse

@app.get("/partials/input/{tab}")
async def get_input_partial(request: Request, tab: str):
    valid_tabs = {"youtube", "pdf", "markdown", "code"}
    if tab not in valid_tabs:
        tab = "youtube"
    return templates.TemplateResponse(f"partials/input_{tab}.html", {"request": request})

@app.get("/api/items/topics")
async def get_topics_partial(request: Request):
    from services.storage import get_topics
    topics = await get_topics(config.DB_PATH)
    return templates.TemplateResponse("partials/sidebar_topics.html",
                                      {"request": request, "topics": topics})

@app.get("/api/items/random")
async def get_random_notes_partial(request: Request):
    from services.storage import get_random_notes
    notes = await get_random_notes(config.DB_PATH, n=4)
    return templates.TemplateResponse("partials/note_list.html",
                                      {"request": request, "notes": notes, "grid": True})
```

- [ ] **Step 9: partials/sidebar_topics.html 작성**

`templates/partials/sidebar_topics.html`:
```html
{% for t in topics %}
<a hx-get="/api/items?topic={{ t.topic | urlencode }}"
   hx-target="#note-list" hx-swap="innerHTML"
   class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-gray-500 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] cursor-pointer transition-colors">
  <span class="w-2 h-2 rounded-full bg-indigo-400"></span>
  {{ t.topic }}
  <span class="ml-auto text-gray-400 text-[11px]">{{ t.count }}</span>
</a>
{% endfor %}
```

- [ ] **Step 10: 서버 재시작 및 UI 확인**

```bash
uvicorn main:app --reload
```

브라우저에서 http://localhost:8000 열기. 확인 사항:
- 네비바, 사이드바, 입력 패널이 정상 표시
- YouTube 탭 / PDF 탭 전환 시 입력창 변경 (HTMX)
- API 비용 위젯이 사이드바 하단에 표시
- 라이트/다크 모드 전환

- [ ] **Step 11: 커밋**

```bash
git add templates/ main.py routers/items.py routers/settings.py
git commit -m "feat: full HTMX frontend with sidebar, note cards, API cost widget"
```

---

## Task 13: 전체 테스트 실행 및 .env 설정

- [ ] **Step 1: .env 파일 생성**

```bash
cp .env.example .env
# .env 편집: ANTHROPIC_API_KEY, OPENAI_API_KEY 입력
```

- [ ] **Step 2: 전체 테스트 실행**

```bash
pytest tests/ -v --tb=short
```

Expected: 모든 테스트 통과

- [ ] **Step 3: 실제 YouTube URL로 smoke test**

```bash
uvicorn main:app --reload
```

브라우저에서 YouTube URL 입력 후 분석하기 클릭. 확인 사항:
- 노트 카드가 목록 상단에 추가됨
- 사이드바 비용 위젯이 갱신됨
- vault/youtube/ 에 .md 파일이 생성됨

- [ ] **Step 4: 최종 커밋**

```bash
git add .
git commit -m "feat: liby MVP complete — YouTube/PDF analysis with HTMX UI"
```

---

## 미구현 항목 (다음 단계)

- `templates/partials/input_markdown.html` — Markdown 직접 입력 패널
- `templates/partials/input_code.html` — Code 붙여넣기 패널
- `routers/markdown.py`, `routers/code.py`
- API 한도 설정 UI (`/settings` 페이지)
- 노트 상세 보기 페이지 (`partials/note_detail.html`)
- 주제 새로 추가 팝업 (`partials/topic_confirm.html`)
