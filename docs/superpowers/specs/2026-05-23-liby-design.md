# liby — 지식 수집 AI Agent 설계 스펙

**작성일**: 2026-05-23  
**상태**: 승인됨

---

## 1. 프로젝트 개요

### 목적
YouTube, PDF, Markdown, Code 등 다양한 출처의 자료를 AI로 자동 요약하고, 웹 기반 인터페이스에서 열람·관리할 수 있는 개인용 지식 수집 도구.

Lilys AI와 유사한 방향성이되, 제텔카스텐(Zettelkasten) 방식의 지식 확장을 지원하고 Obsidian `.md` 파일과 연동 가능한 구조로 설계한다.

### 핵심 단위: 노트
모든 분석 결과물의 기본 단위를 **노트**라 부른다.

### 사용자 범위
초기에는 개인 단독 사용. 이후 멀티유저 확장을 염두에 둔 구조로 설계한다.

---

## 2. 기술 스택

| 레이어 | 기술 |
|--------|------|
| 백엔드 | Python 3.11+, FastAPI |
| 프론트엔드 | Jinja2 템플릿, HTMX, Tailwind CSS |
| DB | SQLite (단일 파일 `liby.db`) |
| 파일 저장 | 로컬 파일시스템 (`vault/`) |
| AI — Anthropic | claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7 |
| AI — OpenAI | gpt-4o-mini, gpt-4o, o1-mini |
| YouTube 자막 | youtube-transcript-api |
| PDF 파싱 | PyMuPDF (fitz) |

---

## 3. 아키텍처

```
Browser (HTMX + Tailwind)
    ↕ HTTP (HTML 조각 반환)
FastAPI (Python)
    ├── YouTube Router   /api/youtube
    ├── PDF Router       /api/pdf
    ├── Items Router     /api/items  (목록·검색·태그)
    └── AI Provider Layer (Claude / GPT 교체 가능)
         ↕
    SQLite (liby.db)  +  Markdown files (vault/)
         ↕
    Anthropic API  /  OpenAI API
```

HTMX가 서버에서 렌더링된 HTML 조각을 받아 페이지 전체 리로드 없이 화면을 업데이트한다.

---

## 4. 입력 소스

| 탭 | 입력 방식 | 처리 방법 |
|----|-----------|-----------|
| YouTube | URL 붙여넣기 | youtube-transcript-api 자막 추출 |
| PDF | 파일 업로드 | PyMuPDF 텍스트 추출 후 청크 분할 |
| Markdown | 직접 작성 / 파일 업로드 | 텍스트 그대로 처리 |
| Code | 코드 직접 붙여넣기 | 언어 감지 후 AI 설명 요약 |

입력창은 상단 탭 클릭 시 해당 입력 패널이 HTMX로 펼쳐지는 드롭다운 방식으로 표시된다.

---

## 5. AI 파이프라인

### 단계별 모델 분리 (Map-Reduce + Chain of Density)

```
Tier 1 — 추출 (소형/저가 모델)
  ├── 원문 수집 및 텍스트 정제
  ├── 청크 분할 (긴 문서 대응)
  └── Map: 청크별 핵심 문장 추출
  모델: claude-haiku-4-5 / gpt-4o-mini

Tier 2 — 요약 (중간 모델)
  ├── Reduce: Map 결과 통합
  ├── 전체 요약 생성 (5~10문장)
  ├── 핵심 포인트 추출 (3~5개)
  ├── 태그 자동 생성 (최대 5개)
  └── 주제 분류 제안
  모델: claude-sonnet-4-6 / gpt-4o

Tier 3 — 인사이트 (추론 모델) ← 상세 정리 모드만
  ├── Chain of Density: 정보 밀도 점진적 향상
  ├── 핵심 논거 / 주장 추출
  ├── 인사이트 ("So what?")
  ├── 탐구할 질문 생성
  └── 제텔카스텐 연결 노트 제안
  모델: claude-opus-4-7 / o1-mini
```

### 요약 모드

| 모드 | 사용 티어 | 소요 시간 | 산출물 |
|------|-----------|-----------|--------|
| 빠른 정리 | Tier 1 + 2 | ~20초 | 전체 요약(5~10문장) + 핵심 포인트(3~5개) + 태그 |
| 상세 정리 | Tier 1 + 2 + 3 | ~60초 | 빠른 정리 전체 + 논거 + 인사이트 + 질문 + 제텔카스텐 연결 |

### 업그레이드 워크플로
빠른 정리로 생성된 노트는 "상세 정리 →" 버튼으로 언제든 Tier 3를 추가 실행할 수 있다. 기존 Tier 1+2 결과는 재사용하며 Tier 3만 새로 실행되어 비용을 최소화한다.

### AI Provider 추상화

```python
class AIProvider:
    def summarize(text, source_type, mode) -> SummaryResult: ...
    def extract_tags(text) -> list[str]: ...
    def suggest_topic(text, existing_topics) -> str: ...

class ClaudeProvider(AIProvider): ...
class OpenAIProvider(AIProvider): ...
```

사용자는 분석 시 Claude / GPT 중 하나를 선택할 수 있으며, 설정에서 기본 제공자를 지정할 수 있다.

---

## 6. SummaryResult 구조

```python
@dataclass
class SummaryResult:
    # Tier 1 — 추출
    title: str
    language: str
    word_count: int
    reading_time_min: int
    sections: list[str]          # 목차 or YouTube 타임스탬프

    # Tier 2 — 빠른 정리
    summary: str                 # 전체 요약 5~10문장
    key_points: list[str]        # 핵심 포인트 3~5개
    tags: list[str]              # 자동 태그 최대 5개
    suggested_topic: str         # 주제 분류 제안
    summary_mode: str            # "quick" | "detailed"

    # Tier 3 — 상세 정리 (None이면 미실행)
    main_arguments: list[str] | None
    insights: list[str] | None
    questions_raised: list[str] | None
    zettel_links: list[int] | None       # 연결 노트 ID 목록
    related_concepts: list[str] | None
```

---

## 7. 데이터 모델

### SQLite — items 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| type | TEXT | "youtube" \| "pdf" \| "markdown" \| "code" |
| title | TEXT | AI가 추출한 제목 |
| source_url | TEXT | YouTube URL 또는 원본 파일명 |
| summary | TEXT | 전체 요약 (5~10문장) |
| key_points | TEXT (JSON) | 핵심 포인트 리스트 |
| sections | TEXT (JSON) | 목차 / 타임스탬프 |
| tags | TEXT (JSON) | 태그 배열 |
| topic | TEXT | 주제 분류 |
| summary_mode | TEXT | "quick" \| "detailed" |
| main_arguments | TEXT (JSON) | 핵심 논거 (상세만) |
| insights | TEXT (JSON) | 인사이트 (상세만) |
| questions_raised | TEXT (JSON) | 탐구 질문 (상세만) |
| zettel_links | TEXT (JSON) | 연결 노트 ID 목록 (상세만) |
| related_concepts | TEXT (JSON) | 연관 개념 키워드 (상세만) |
| ai_provider | TEXT | "claude" \| "gpt" |
| ai_models | TEXT (JSON) | 사용된 모델명 배열 |
| api_cost_usd | REAL | 해당 노트 분석 비용 |
| md_file_path | TEXT | 내보낸 .md 파일 경로 |
| created_at | DATETIME | 생성 일시 |
| updated_at | DATETIME | 마지막 수정 일시 |

### Markdown 파일 구조

```
liby/
├── vault/
│   ├── youtube/
│   │   └── 2026-05-23-llm-karpathy.md
│   ├── pdf/
│   │   └── 2026-05-23-attention-is-all-you-need.md
│   ├── markdown/
│   └── code/
└── liby.db
```

Markdown 파일 포맷:
```markdown
---
title: "LLM이 세상을 바꾸는 방법"
type: youtube
source: https://youtube.com/watch?v=...
tags: [AI, LLM, 강의]
topic: AI / ML
ai_provider: claude
summary_mode: detailed
created: 2026-05-23
---

## 요약
...5~10문장 요약...

## 핵심 포인트
- 포인트 1
- 포인트 2

## 인사이트
- 인사이트 1

## 탐구할 질문
- 질문 1

## 연결 노트
- [[2026-05-20-transformer-paper]]
```

---

## 8. UI 설계

### 색상 팔레트

| 용도 | HEX | 비율 |
|------|-----|------|
| 배경 (화이트) | `#FFFFFF` | 60~70% |
| 메인 그린 | `#1F6F4A` | 10~15% |
| 세이지 그린 | `#A8CBB2` | 10~15% |
| 본문 텍스트 (차콜) | `#1F2937` | 10~15% |
| 구분선/서브 배경 | `#F3F5F4` | 5~10% |

다크 모드 지원. 상단 우측 토글 버튼으로 전환.

### 레이아웃 구성

```
┌─────────────────────────────────────────────────┐
│ 📚 liby │ YouTube │ PDF │ Markdown │ Code │ [다크모드] │  ← 네비바
├─────────────────────────────────────────────────┤
│ [URL 입력창 ................] [Claude▾][빠른정리▾][분석하기] │  ← 입력 패널 (탭 클릭 시 토글)
├──────────┬──────────────────────────────────────┤
│ 전체 노트 │  최근 업데이트                        │
│  ─────   │  ┌──────────────────────────────────┐│
│ 주제별   │  │ [YouTube] 제목                   ││
│  AI/ML 5 │  │ 방금 전 · Claude · [상세 정리]    ││
│  논문  4 │  │ 요약 미리보기 2~3줄...            ││
│  강의  2 │  │ #AI #LLM  [AI/ML]  $0.009        ││
│  + 추가  │  │              [전체 보기] [.md 열기]││
│          │  └──────────────────────────────────┘│
│ 태그 검색│  ┌──────────────────────────────────┐│
│ [입력...]│  │ [PDF] 제목                       ││
│ #AI ×    │  │ ...                  [상세 정리→]││
│ #LLM ×   │  └──────────────────────────────────┘│
│          │                                       │
│ ──────── │  오늘의 추천 노트                     │
│ API 비용 │  ┌──────────┐ ┌──────────┐           │
│ Claude   │  │ [PDF]    │ │ [YouTube]│           │
│ $0.89/$2 │  │ 제목...  │ │ 제목...  │           │
│ ▓▓▓▓░░░  │  └──────────┘ └──────────┘           │
│ GPT      │                                       │
│ $1.71/$2 │                                       │
│ ▓▓▓▓▓▓▓░ │                                       │
│ ① API ✓  │                                       │
│ ② Claude Code                                   │
│ ③ Codex  │                                       │
└──────────┴───────────────────────────────────────┘
```

### 주요 UI 동작

- **입력 패널**: 탭(YouTube/PDF/Markdown/Code) 클릭 시 HTMX로 해당 입력창 토글
- **주제 분류**: AI가 기존 주제 목록을 참고해 자동 배정. 일치하는 주제 없으면 사용자에게 새 주제명 제안 → 수락/거부/수정 선택 가능. 거부 시 "미분류"로 임시 저장
- **태그 검색**: 여러 태그 동시 선택 가능, 선택된 태그 배지로 표시 및 개별 제거
- **상세 정리 업그레이드**: 빠른 정리 노트 카드에 "상세 정리 →" 버튼 표시. 클릭 시 Tier 3만 추가 실행. 완료 후 `summary_mode`가 "detailed"로 업데이트됨
- **오늘의 추천 노트**: 전체 노트에서 랜덤 4개 선택. 앱 시작 시마다 새로 뽑음
- **이모지**: 로고(`📚 liby`) 제외 전체 UI에서 이모지 미사용

---

## 9. API 비용 모니터링

### 데이터 수집
- 노트 분석 시 사용된 모델, 입력/출력 토큰 수, 계산된 비용을 `items` 테이블에 기록

### 사이드바 하단 위젯
- Claude / GPT 각각 독립 표시
- 이번 달(캘린더 월 기준) 사용액 + 설정 한도 대비 진행 바
- 상태 배지: 정상 / 임박(한도의 80%↑) / 초과

### API 폴백 체인
```
① Anthropic API / OpenAI API  ← 기본
② Claude Code CLI             ← API 한도 초과 시
③ Codex CLI                   ← Claude Code 미설치 or 오류 시
④ 오류 반환 + 사용자 안내
```

Claude Code CLI와 Codex CLI는 서브프로세스(`subprocess.run`)로 호출. 설치 여부는 시작 시 자동 감지.

---

## 10. 파일 구조 (구현 예상)

```
liby/
├── main.py                    # FastAPI 진입점
├── routers/
│   ├── youtube.py
│   ├── pdf.py
│   ├── items.py
│   └── settings.py
├── services/
│   ├── ai/
│   │   ├── base.py            # AIProvider 추상 클래스
│   │   ├── claude.py          # ClaudeProvider
│   │   ├── openai.py          # OpenAIProvider
│   │   └── fallback.py        # Claude Code / Codex CLI 폴백
│   ├── extractor.py           # youtube-transcript-api, PyMuPDF
│   └── storage.py             # DB 저장 + .md 파일 생성
├── models.py                  # SQLite 스키마 (SQLModel or raw sqlite3)
├── templates/                 # Jinja2 HTML 템플릿
│   ├── base.html
│   ├── index.html
│   └── partials/              # HTMX 응답용 HTML 조각
├── static/
│   └── (Tailwind CSS 빌드 결과)
├── vault/                     # Markdown 파일 저장
│   ├── youtube/
│   └── pdf/
├── liby.db
└── config.py                  # API Key, 한도, 기본 모델 설정
```

---

## 11. 미결 사항

- Markdown / Code 입력에 대한 상세 처리 방식 (빠른 정리만 지원할지, 상세도 지원할지)
- API 한도 기본값 및 설정 UI 세부 구성
- 다중 사용자 전환 시 인증 방식 (추후 범위)
