# liby

개인용 지식 수집 AI 라이브러리. YouTube 영상, PDF, 텍스트, Markdown, 코드를 붙여넣으면 AI가 Lilys 스타일의 구조화된 요약 노트를 만들어 주고, 웹 UI에서 열람·검색·관리할 수 있습니다.

> A personal knowledge library: paste a YouTube URL, PDF, text, or code and get an AI-generated structured summary note, browsable in a local web UI.

## 주요 기능

- **다양한 입력 소스** — YouTube(자막 자동 추출, yt-dlp), PDF(PyMuPDF), 일반 텍스트, Markdown, 코드
- **2단계 요약 모드** — 빠른 요약(quick)과 챕터·인용·각주가 포함된 상세 요약(detailed)
- **YouTube 타임라인 연동** — 요약 문단의 타임스탬프 클릭 시 임베드 플레이어가 해당 지점으로 이동
- **프로젝트/토픽 관리** — 노트를 프로젝트·토픽으로 묶고 프로젝트 다이제스트 생성
- **AI 프로바이더 교체 가능** — Anthropic API, OpenAI API, 또는 [agent-runner-bridge](docs/operations-discord-tailscale.md)를 통한 Claude Code/Codex CLI(구독 인증, 추가 비용 없음)
- **비용 가드** — 프로바이더별 월간 사용액 한도 및 사용량 대시보드
- **Discord 봇 연동(선택)** — 폰에서 Discord 메시지로 분석을 트리거하고, Tailscale로 결과 열람 ([운영 가이드](docs/operations-discord-tailscale.md))
- **Obsidian 친화적 저장** — 모든 노트는 SQLite + `vault/`의 Markdown 파일로 저장

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 백엔드 | Python 3.11+, FastAPI |
| 프론트엔드 | Jinja2 + HTMX + Tailwind CSS (빌드 단계 없음) |
| 저장소 | SQLite(`liby.db`) + Markdown 파일(`vault/`) |
| AI | Anthropic Claude / OpenAI GPT / CLI bridge |

## 시작하기

```bash
git clone <this-repo>
cd liby
python -m venv .venv
# Windows: .venv\Scripts\activate / macOS·Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키·설정 입력
python -m uvicorn main:app --port 8000
```

브라우저에서 http://127.0.0.1:8000 접속.

### .env 설정

최소한 AI 프로바이더 하나는 설정해야 합니다. [.env.example](.env.example)에 전체 항목과 설명이 있습니다.

| 프로바이더 | `DEFAULT_AI_PROVIDER` | 필요 설정 |
|-----------|----------------------|----------|
| Anthropic API | `claude` | `ANTHROPIC_API_KEY` |
| OpenAI API | `gpt` | `OPENAI_API_KEY` |
| Claude Code CLI (bridge) | `claude-cli` | `BRIDGE_BASE_URL`, `BRIDGE_TOKEN` |
| Codex CLI (bridge) | `codex-cli` | `BRIDGE_BASE_URL`, `BRIDGE_TOKEN` |

Discord 봇·외부 열람(Tailscale)은 선택 사항이며 [docs/operations-discord-tailscale.md](docs/operations-discord-tailscale.md)를 참고하세요.

## 테스트

```bash
python -m pytest
```

외부 API 호출은 모두 모킹되어 있어 네트워크나 API 키 없이 실행됩니다.

## 프로젝트 구조

```
main.py            # FastAPI 앱 진입점 (worker + Discord 봇 lifespan)
config.py          # .env 기반 설정
models.py          # SQLite 스키마/초기화
routers/           # API 라우터 (youtube, pdf, text, code, items, projects, ...)
services/          # 추출·요약·태스크 큐·Discord 봇
services/ai/       # AI 프로바이더 추상화 (claude / openai / bridge / fallback)
templates/         # Jinja2 + HTMX 템플릿
vault/             # 생성된 Markdown 노트 (gitignore)
docs/              # 설계 스펙·구현 계획·운영 가이드
```

## 라이선스

[MIT](LICENSE)
