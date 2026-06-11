# 공개 패키징 (Docker + bridge 통합 + 영문 README) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker compose up` 한 번으로 liby + agent-runner-bridge(구독 인증)가 함께 뜨는 공개용 패키지를 만들고, 영문 README와 스크린샷을 갖춘다.

**Architecture:** liby 앱은 루트 유지, bridge는 `bridge/` 하위 디렉토리로 추적 파일만 복사(자체 완결 — 추후 분리 용이). 루트 compose가 두 서비스를 오케스트레이션하고, 구독 creds는 사용자 로컬에서 `bridge/creds/`(gitignore)로 주입.

**Tech Stack:** Docker, docker compose, python:3.13-slim + ffmpeg, node:20(bridge), GitHub Actions, Playwright(스크린샷).

**Spec:** `docs/superpowers/specs/2026-06-10-public-packaging-docker-bridge-design.md`

---

### Task 1: bridge/ 디렉토리 가져오기 + .gitignore 보강

**Files:**
- Create: `bridge/` (agent-runner-bridge의 git 추적 파일 23개 복사)
- Modify: `.gitignore`

- [x] **Step 1: 추적 파일만 복사** (히스토리·creds·.env·node_modules 제외)

```bash
mkdir -p /c/Projects/liby/bridge
cd /c/Projects/code_agent/agent-runner-bridge && git ls-files -z | tar --null -cf - -T - | (cd /c/Projects/liby/bridge && tar -xf -)
```

- [x] **Step 2: 루트 .gitignore에 추가**

```
# bridge (하위 디렉토리 — 로컬 산출물·인증 정보 제외)
bridge/node_modules/
bridge/dist/
bridge/creds/
bridge/.env
bridge/workspace/
data/
```

- [x] **Step 3: PII 스캔** — `git grep` 대상이 되도록 `git add bridge` 후:

```bash
git diff --cached | grep -aiE '(juhyeon|gmail|Users[/\\]ju|sk-ant-api|[0-9]{17,19})'  # 빈 출력 기대 (sk-ant-... 플레이스홀더 제외)
git ls-files --cached bridge | grep -E '(creds|\.env$|node_modules)'  # 빈 출력 기대
```

- [x] **Step 4: Commit** — `feat(bridge): agent-runner-bridge를 하위 디렉토리로 통합 (추적 파일만)`

### Task 2: bridge/scripts/sync-creds.sh (macOS/Linux용)

**Files:**
- Create: `bridge/scripts/sync-creds.sh`

- [x] **Step 1: 스크립트 작성** (ps1과 동등 동작)

```sh
#!/usr/bin/env sh
# POSIX equivalent of sync-creds.ps1: copies your local Claude/Codex subscription
# credentials into ./creds so the container can mount credential-ONLY directories.
# Run once after logging in on the host (and again whenever tokens refresh):
#   ./scripts/sync-creds.sh
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$root/creds/claude" "$root/creds/codex"

if [ -f "$HOME/.claude/.credentials.json" ]; then
  cp "$HOME/.claude/.credentials.json" "$root/creds/claude/.credentials.json"
  echo "synced claude credentials"
else
  echo "warning: no Claude credentials at ~/.claude/.credentials.json (run 'claude' and log in first)" >&2
fi

if [ -f "$HOME/.codex/auth.json" ]; then
  cp "$HOME/.codex/auth.json" "$root/creds/codex/auth.json"
  echo "synced codex credentials"
else
  echo "warning: no Codex credentials at ~/.codex/auth.json (run 'codex' and log in first)" >&2
fi
```

- [x] **Step 2: 실행 비트 설정** — `git add` 후 `git update-index --chmod=+x bridge/scripts/sync-creds.sh`
- [x] **Step 3: 문법 검증** — `sh -n bridge/scripts/sync-creds.sh` (출력 없음 기대)
- [x] **Step 4: Commit** — `feat(bridge): macOS/Linux용 sync-creds.sh 추가`

### Task 3: liby Dockerfile + .dockerignore

**Files:**
- Create: `Dockerfile`, `.dockerignore`

- [x] **Step 1: Dockerfile 작성**

```dockerfile
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# ffmpeg: YouTube 챕터 스크린샷용 (없으면 해당 기능만 비활성 — 이미지는 완전체 제공)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m liby && mkdir -p /data && chown -R liby:liby /data /app
USER liby

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [x] **Step 2: .dockerignore 작성**

```
.git
.github
.claude
.superpowers
.playwright-mcp
.pytest_cache
__pycache__
*.pyc
.venv
venv
.env
liby.db*
demo.db*
server.log
vault/
demo-vault/
data/
docs/
tests/
bridge/
lilys_sample.txt
*.png
README*.md
LICENSE
```

- [x] **Step 3: 빌드 검증** — `docker build -t liby:dev .` 성공 기대 (Docker 미가용 시 CI로 위임하고 명시)
- [x] **Step 4: Commit** — `feat(docker): liby 앱 Dockerfile + .dockerignore`

### Task 4: 루트 docker-compose.yml + .env.example 갱신

**Files:**
- Create: `docker-compose.yml`
- Modify: `.env.example`

- [x] **Step 1: compose 작성**

```yaml
services:
  liby:
    build: .
    image: liby:latest
    ports:
      - "8000:8000"
    environment:
      DB_PATH: /data/liby.db
      VAULT_PATH: /data/vault
      DEFAULT_AI_PROVIDER: ${DEFAULT_AI_PROVIDER:-claude-cli}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      CLAUDE_MONTHLY_LIMIT_USD: ${CLAUDE_MONTHLY_LIMIT_USD:-2.00}
      GPT_MONTHLY_LIMIT_USD: ${GPT_MONTHLY_LIMIT_USD:-2.00}
      # bridge 서비스로 자동 연결 (compose 내부 DNS)
      BRIDGE_BASE_URL: http://bridge:8787
      BRIDGE_TOKEN: ${BRIDGE_TOKEN:-}
      BRIDGE_CWD: /workspace
      DISCORD_LIBY_TOKEN: ${DISCORD_LIBY_TOKEN:-}
      DISCORD_LIBY_CHANNEL_ID: ${DISCORD_LIBY_CHANNEL_ID:-}
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://127.0.0.1:8000}
      BOT_API_TOKEN: ${BOT_API_TOKEN:-}
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  # 구독 인증(Claude Pro / ChatGPT Plus) 또는 API 키로 CLI 에이전트를 실행하는 게이트웨이.
  # API 키만 쓸 경우: docker compose up liby 로 단독 실행 가능.
  bridge:
    build: ./bridge
    image: agent-runner-bridge:latest
    environment:
      HOST: 0.0.0.0
      PORT: 8787
      BRIDGE_TOKEN: ${BRIDGE_TOKEN:?set BRIDGE_TOKEN in .env}
      WORKSPACE_ALLOWLIST: /workspace
      ENV_ALLOWLIST: OPENAI_API_KEY,ANTHROPIC_API_KEY
      AUTH_PREFERENCE: ${AUTH_PREFERENCE:-local}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      CLAUDE_MONTHLY_LIMIT_USD: ${CLAUDE_MONTHLY_LIMIT_USD:-}
      GPT_MONTHLY_LIMIT_USD: ${GPT_MONTHLY_LIMIT_USD:-}
      USAGE_LEDGER_PATH: /data/usage-ledger.json
      GRACE_SEC: ${GRACE_SEC:-5}
    volumes:
      - liby-runs:/workspace
      - bridge-ledger:/data
      # 구독 로그인: 호스트에서 claude/codex 로그인 → sync-creds 실행 시 채워짐.
      # 디렉토리가 비어 있으면 API 키 폴백으로 동작 (무해).
      - ./bridge/creds/claude:/home/node/.claude
      - ./bridge/creds/codex:/home/node/.codex
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:8787/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

volumes:
  liby-runs:
  bridge-ledger:
```

- [x] **Step 2: .env.example에 compose 안내 반영** — BRIDGE 섹션 주석을 "compose 사용 시 BRIDGE_BASE_URL/BRIDGE_CWD는 자동 설정, BRIDGE_TOKEN만 필수(임의 긴 문자열)"로 갱신
- [x] **Step 3: 검증** — `BRIDGE_TOKEN=dummy docker compose config -q` (출력 없음=유효)
- [x] **Step 4: Commit** — `feat(docker): 루트 compose — liby + bridge 동시 기동, 구독 creds 마운트`

### Task 5: CI 확장 (bridge 테스트 + docker build)

**Files:**
- Modify: `.github/workflows/ci.yml`

- [x] **Step 1: 잡 추가**

```yaml
  bridge:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: bridge
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: bridge/package-lock.json
      - run: npm ci
      - run: npm run typecheck
      - run: npm test

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t liby:ci .
      - run: docker build -t agent-runner-bridge:ci ./bridge
```

- [x] **Step 2: 로컬 검증 가능한 범위 확인** — bridge: `cd bridge && npm ci && npm run typecheck && npm test` (호스트에 node 있으면 실행)
- [x] **Step 3: Commit** — `ci: bridge(typecheck+vitest)·docker build 검증 잡 추가`

### Task 6: 데모 시드 + 스크린샷

**Files:**
- Create: `scripts/demo_seed.py`, `docs/images/home-light.png`, `docs/images/home-dark.png`

- [x] **Step 1: 시드 스크립트 작성** — 실 DB 미사용, `DB_PATH`/`VAULT_PATH` 환경변수로 대상 지정

```python
"""데모용 노트를 빈 DB에 삽입한다 (스크린샷·체험용 — 실 데이터 불필요).

사용: DB_PATH=./demo.db VAULT_PATH=./demo-vault python scripts/demo_seed.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from models import init_db
from services.ai.base import SummaryResult
from services.storage import save_note

NOTES = [
    SummaryResult(
        title="트랜스포머 아키텍처 한 시간 정리",
        language="ko", word_count=8400, reading_time_min=6,
        sections=[], summary="어텐션 메커니즘이 RNN의 순차 처리 한계를 어떻게 극복하는지를 셀프 어텐션, 멀티헤드, 포지셔널 인코딩 순으로 설명한다.",
        key_points=["셀프 어텐션은 시퀀스 전체를 한 번에 본다", "멀티헤드는 서로 다른 관계를 병렬로 학습", "인코더-디코더 구조의 분업"],
        tags=["AI", "딥러닝", "트랜스포머"], suggested_topic="머신러닝",
        summary_mode="quick",
        paragraphs=[{"text": "어텐션은 쿼리·키·밸류의 가중합으로 문맥을 만든다.", "t": 312}],
    ),
    SummaryResult(
        title="SQLite는 어떻게 단일 파일로 ACID를 보장하는가",
        language="ko", word_count=5200, reading_time_min=4,
        sections=[], summary="WAL 모드와 저널링이 어떻게 동시성과 내구성을 동시에 제공하는지 내부 구조 중심으로 다룬다.",
        key_points=["WAL은 읽기와 쓰기를 분리한다", "체크포인트 주기가 성능을 좌우", "단일 작성자 모델의 트레이드오프"],
        tags=["데이터베이스", "SQLite"], suggested_topic="데이터베이스",
        summary_mode="quick",
        paragraphs=[{"text": "WAL 파일은 커밋 로그이자 읽기 스냅샷의 원천이다."}],
    ),
    SummaryResult(
        title="개인 지식 관리, 수집보다 연결이 중요하다",
        language="ko", word_count=3100, reading_time_min=3,
        sections=[], summary="제텔카스텐의 핵심은 노트의 양이 아니라 노트 사이의 연결 밀도라는 주장. 수집 단계에서 연결 후보를 만드는 습관을 제안한다.",
        key_points=["연결 없는 수집은 디지털 창고", "요약 시점에 태그·토픽을 강제하는 이유", "재방문 트리거 설계"],
        tags=["PKM", "제텔카스텐"], suggested_topic="지식관리",
        summary_mode="quick",
        paragraphs=[{"text": "노트는 쓰는 순간이 아니라 다시 만나는 순간 가치가 생긴다."}],
    ),
]

async def main() -> None:
    assert "demo" in config.DB_PATH, f"실 DB 보호: DB_PATH에 'demo'가 포함돼야 함 ({config.DB_PATH})"
    await init_db()
    types_urls = [
        ("youtube", "https://youtu.be/dQw4w9WgXcQ"),
        ("text", ""),
        ("markdown", ""),
    ]
    for result, (src_type, url) in zip(NOTES, types_urls):
        nid = await save_note(config.DB_PATH, config.VAULT_PATH, src_type, url, result, "claude-cli")
        print(f"seeded note #{nid}: {result.title}")

if __name__ == "__main__":
    asyncio.run(main())
```

- [x] **Step 2: 시드 실행** — `DB_PATH=./demo.db VAULT_PATH=./demo-vault python scripts/demo_seed.py` → 3건 출력 기대
- [x] **Step 3: 데모 서버 기동** — `DB_PATH=./demo.db VAULT_PATH=./demo-vault python -m uvicorn main:app --port 8003` (백그라운드)
- [x] **Step 4: Playwright 캡처** — `http://127.0.0.1:8003` 라이트 1장, `localStorage.theme=dark` 후 다크 1장 → `docs/images/home-light.png`, `docs/images/home-dark.png` (1280×800)
- [x] **Step 5: 정리** — 서버 종료, `demo.db`·`demo-vault/` 삭제, `.gitignore`에 `demo.db*`, `demo-vault/` 추가
- [x] **Step 6: Commit** — `docs: 데모 시드 스크립트 + UI 스크린샷`

### Task 7: README 영문 메인 + 한국어 보조

**Files:**
- Create: `README.ko.md` (현 README 이동·갱신)
- Modify: `README.md` (영문 신규)

- [x] **Step 1: README.ko.md 생성** — 현 한국어 README 내용 이동 + Docker/구독 모드 Quick Start 섹션 추가 + 상단에 `[English](README.md)` 링크
- [x] **Step 2: README.md 영문 작성** — 구조: 한 줄 소개 → 뱃지(CI·MIT) → 언어 링크 → 스크린샷 → Features → Quick start (Docker: Option A API 키 / Option B 구독 sync-creds 3단계, 수동 설치 보조) → Configuration 표 → Architecture → Notes & limitations (한국어 중심 UI, 토큰 갱신 시 sync-creds 재실행, 본인 계정만 사용) → Development(pytest, bridge vitest) → License
- [x] **Step 3: 링크 검증** — README 내 상대 링크 대상 파일 존재 확인 (`README.ko.md`, `LICENSE`, `docs/images/*.png`, `bridge/README.md`, `docs/operations-discord-tailscale.md`, `.env.example`)
- [x] **Step 4: Commit** — `docs: 영문 README 메인 + 한국어 README.ko.md`

### Task 8: 최종 검증

- [x] **Step 1: pytest** — `python -m pytest -q` → 266 passed 기대
- [x] **Step 2: bridge 테스트** — `cd bridge && npm test` (로컬 node 가용 시; 아니면 CI 위임 명시)
- [x] **Step 3: compose 스모크** — `BRIDGE_TOKEN=dummy docker compose up -d liby` → `curl http://127.0.0.1:8000/` 200 → `docker compose down` (Docker 가용 시)
- [x] **Step 4: PII 재스캔** — `git ls-files | xargs grep -lE '(juhyeon001@gmail|Users[/\\]ju[/\\])' ` 빈 출력, `git ls-files | grep -E '(creds/|\.env$|demo\.db)'` 빈 출력
- [x] **Step 5: Commit (잔여분)** — 플랜 체크박스 갱신 커밋
