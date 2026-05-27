# Lilys 스타일 상세 요약 양식 설계

**작성일:** 2026-05-28

## 개요 (Overview)

liby의 **상세 정리(detailed)** 요약 출력을 Lilys AI 양식에 가깝게 바꾼다.
현재 상세 요약은 평면 구조(요약 문단 + 핵심 포인트/핵심 논거/인사이트/탐구할 질문의 단순 불릿 리스트)다.
Lilys는 계층 구조다: 한 줄 요약 → 목차 → 번호형 계층 섹션(`1.` / `1.1`) → 굵은 소제목 + 다단계 중첩 불릿 → (youtube) 타임스탬프 출처.

**목표:** 상세 정리 시 한 줄 요약 + 목차 + 계층형 본문(굵은 소제목 + 중첩 불릿)을 생성하고,
youtube 노트는 각 섹션/항목에 타임스탬프를 붙여 모달 임베드 영상에서 클릭 시 해당 시점으로 이동한다.

## 확정된 결정 사항 (브레인스토밍 합의)

- **범위(Tier B):** 구조(한 줄 요약 + 목차 + 계층 섹션 + 굵은 소제목 + 중첩 불릿) + youtube 타임스탬프 출처.
  - 비범위: 키워드 하이라이트, 영상 프레임 캡처 이미지, AI 생성 SVG 다이어그램(Tier C — 추후).
- **detailed 전용:** quick 모드는 현행 유지(요약 문단 + 핵심 포인트).
- **분석 섹션:** 계층 본문 하단에 **인사이트 + 탐구할 질문**만 보존. **핵심 논거 제거**(계층 본문과 중복).
- **생성 방식(1안):** detailed일 때 tier2가 계층형 `sections`를 직접 생성. tier3는 인사이트/질문만 생성하도록 축소.

## 데이터 모델

`SummaryResult.sections`(현재 `list[str]`, 항상 빈 배열로 미사용)를 계층 구조로 재정의한다.

```jsonc
sections: [                                  // H2 섹션 목록
  {
    "heading": "1. OpenClaw 기반 자동매매 봇",
    "t": 150,                                // 선택: 시작 시각(초). youtube만, 그 외 생략/null
    "subsections": [                         // H3 목록
      {
        "heading": "1.1 OpenClaw 소개",
        "t": 36,
        "items": [                           // 굵은 lead 불릿
          {
            "lead": "OpenClaw 소개",
            "t": 36,
            "bullets": ["24시간 시장 감시·자동매매", "오래된 PC에도 설치"]
          }
        ]
      }
    ]
  }
]
```

- `t`: 정수 초. youtube detailed만 채움. `_build_chapters`의 가드 캐스팅(`int(float(...))`, 실패 시 누락) 재사용 패턴.
- **목차(TOC)는 저장하지 않음** — 렌더 시 `sections`의 heading/subsection.heading에서 파생.
- `summary`: 상단 한 줄 요약(2~3문장)으로 사용.
- DB: `items.sections`는 이미 JSON TEXT이며 `_JSON_FIELDS`에 포함되어 자동 역직렬화됨 → **마이그레이션 불필요**.
- 잘못된 구조(딕셔너리 누락, 타입 오류)는 빈 리스트로 폴백 — `summary`/`insights`/`questions`는 유지.

## 컴포넌트

### 1. AI 프롬프트 (`services/ai/claude.py`, `services/ai/openai_provider.py`)

- **detailed 전용 tier2 프롬프트** 신설(또는 기존 tier2를 mode 분기). detailed일 때 요청 JSON에 계층 `sections`를 포함:
  - 5~12개 의미 단위 H2 섹션, 각 H2 아래 H3, 각 H3 아래 굵은 lead 항목 + 2~5개 하위 불릿.
  - heading은 `1.`, `1.1` 번호 접두.
  - **입력에 `[m:ss]` 타임스탬프가 있으면** 각 heading/lead에 `t`(초)를 붙이고, 없으면 생략.
- **tier3 프롬프트 축소:** `insights`, `questions_raised`만 생성(`main_arguments`/`related_concepts` 제거).
- 파싱: 기존 `_parse_json` 재사용. `sections` 빌드 헬퍼(`_build_sections(data)`)가 가드하여 정상 항목만 수집, 실패 시 `[]`.
- quick 프롬프트/경로는 변경하지 않는다.

### 2. 추출/요약 연결 (`routers/youtube.py`, `services/ai` 인터페이스)

- youtube + detailed: `summarize`에 **타임스탬프 자막**(`segments_to_transcript(segments)`)을 본문 텍스트로 전달 → AI가 `[m:ss]`를 보고 `t`를 부여. quick이나 비youtube는 평문 전달(현행).
  - 인터페이스: `summarize(text, source_type, mode, existing_topics)`의 `text`로 youtube-detailed면 타임스탬프 자막을 넘긴다(추가 인자 없이 호출부에서 선택).
- 비youtube(pdf/code/text) detailed: 평문 입력 → `t` 없는 계층 sections.

### 3. 저장 (`services/storage.py`)

- `_make_md_content`를 계층 렌더로 확장:
  - `## 요약`(한 줄 요약)
  - `## 목차` — `1. ...` / `  1.1 ...` 들여쓰기 목록
  - 본문: `## {heading}` / `### {heading}` + `- **{lead}** ({m:ss})` + `  - {bullet}`
  - 끝에 `## 인사이트`, `## 탐구할 질문`(있을 때)
  - quick(=sections 비어있음)이면 기존 평면 출력 유지.
- 타임스탬프는 마크다운에서 `(m:ss)` 텍스트로(앵커/링크 없이) 표기.

### 4. 모달 렌더 (`templates/partials/note_detail_modal.html`)

- 기존 영상 임베드 + 챕터 블록 유지.
- 요약 아래에 계층 본문 추가(상세 정리이고 `sections`가 있을 때):
  - **목차**: sections heading 앵커 목록(클릭 시 모달 내 스크롤).
  - **본문**: H2/H3 + 굵은 lead + (있으면) `⏱m:ss` 버튼(`onclick="ytSeek(t)"`, youtube만) + 중첩 불릿.
  - 시:분:초 포맷은 기존 `"%d:%02d:%02d"|format(...)` 분기 재사용.
- 하단에 인사이트/탐구할 질문(기존 블록 유지), 핵심 논거 블록 제거.
- `sections`가 비면(quick 등) 기존 핵심 포인트 블록 표시.

### 5. 상세 정리 업그레이드 버튼 (`routers/items.py` `upgrade_note`)

- youtube: 이미 `extract_youtube_full`로 재추출하므로 detailed `summarize`(타임스탬프 자막)로 계층 sections 생성 → `sections`/`insights`/`questions` 갱신.
- pdf/text: 전체 텍스트 부재 → 계층 sections 생성 불가, 기존 tier3 인사이트/질문 동작 유지(한계).
- code: github URL 재추출 가능하나 1차 범위에서는 기존 동작 유지(후속).

## 데이터 흐름 예시 (youtube detailed)

1. 분석: `extract_youtube_full` → detailed면 `segments_to_transcript`를 요약 입력으로 → tier2가 계층 `sections`(+`t`) 생성 → tier3가 인사이트/질문 → `save_note`로 `sections` 저장.
2. 모달 열기: 한 줄 요약 + 목차 + 계층 본문(⏱ 포함) + 인사이트/질문 렌더.
3. 챕터/본문 `⏱` 클릭 → `ytSeek(t)` → 임베드 영상 이동.

## 비목표 (Non-goals)

- 키워드 하이라이트, 영상 프레임 캡처 이미지, AI 생성 SVG 다이어그램(Tier C).
- quick 모드 양식 변경.
- pdf/text 업그레이드 시 계층 재생성(전체 텍스트 미보관).
- 마크다운 내 타임스탬프 클릭 링크(텍스트 표기만).

## 테스트 고려사항

- **프롬프트 파싱:** mock 응답으로 계층 `sections` 빌드(타임스탬프 유/무), 잘못된 구조 → `[]` 폴백, 인사이트/질문 유지.
- **storage:** detailed sections가 마크다운 계층(##/###/굵은 lead/중첩 불릿)으로 렌더, quick은 평면 유지.
- **라우터:** youtube detailed가 타임스탬프 포함 sections 저장, quick은 sections 빈 채 평면(회귀 없음).
- **모달:** 브라우저 수동 검증 — 목차 앵커, H2/H3 + lead, `⏱` 클릭 시 영상 이동, 인사이트/질문 하단 표시, 핵심 논거 미표시.
