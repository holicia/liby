# liby-mini — PDF 논문 요약 전용 경량판 설계 스펙

**작성일**: 2026-06-17
**상태**: 승인됨

---

## 1. 목적

회사에서 혼자 쓸 수 있는, **PDF 논문 요약만** 하는 liby 경량판. 기존 liby의
검증된 논문 요약 파이프라인(5섹션 + 본문 그림 인라인)을 그대로 가져오되,
YouTube·Discord·텍스트/코드 입력 등 부가 기능을 모두 제거해 의존성과 코드를
최소화한다. 회사 PC에 폴더째 복사/zip해서 `docker compose up` 한 번으로 띄운다.

## 2. 위치·형태

- `C:\Projects\liby-mini\` — liby와 분리된 **자체 완결 폴더**(독립 git/배포).
- liby의 PDF 관련 코드를 **복사**해 가져온다(이후 독립 유지, 동기화 의무 없음).

## 3. LLM 경로 — 로컬 Claude Code(bridge) 활용

- 별도 API/OpenAI 엔드포인트를 쓰지 않는다. **liby가 현재 쓰는 bridge + 로컬
  `claude` CLI** 경로를 그대로 재사용한다.
- 회사 PC의 Claude Code가 **AWS Bedrock**으로 설정돼 있으면, bridge가 그 `claude`를
  호출하므로 자동으로 Bedrock Claude를 사용한다(앱은 provider-agnostic).
- 따라서 liby-mini도 `bridge/`(agent-runner-bridge)를 번들하고 compose로 함께 띄운다.

### Bedrock 자격증명 전달 — 두 방식 모두 지원
bridge 컨테이너의 `claude` CLI가 Bedrock에 접근하려면 AWS 자격증명 + Bedrock 모드가
필요하다. 두 경로를 **모두** docker-compose에서 지원하고, 실제 회사 환경에서 맞는 쪽만
.env로 켠다.

1. **`~/.aws` 마운트 방식**: 호스트의 `${AWS_SHARED_DIR:-~/.aws}`를 bridge의
   `/home/node/.aws`(읽기전용)로 마운트. 프로파일 기반 자격증명 사용.
2. **환경변수 방식**: `.env`의 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `AWS_SESSION_TOKEN`(선택)을 bridge에 주입.
- 공통: `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`(예: us-east-1),
  `ANTHROPIC_MODEL`(Bedrock 모델 ID, 예: 미국 inference profile)을 bridge env로 전달.
  bridge의 `ENV_ALLOWLIST`에 AWS·Bedrock 변수를 추가해 `claude`에 전파되게 한다.
- 자격증명/OAuth 파일은 전부 gitignore. 셋업 절차는 README에 명시.
- 기존 OAuth(`sync-creds`) 방식도 그대로 남겨, 구독 인증 PC에서도 동작하게 한다.

## 4. 아키텍처

단일 앱 컨테이너 + bridge 컨테이너(compose 2개, 한 명령).

```
liby-mini/
├── main.py            FastAPI 앱 (lifespan: init_db + 워커)
├── config.py          .env 설정 (BRIDGE_*, DB_PATH, VAULT_PATH, LIBY_PORT)
├── models.py          SQLite items 테이블 (논문 전용 최소 컬럼)
├── routers/
│   ├── pdf.py         POST /api/pdf — 업로드→그림추출→요약→저장
│   └── items.py       목록/검색/상세/전체화면(read)/삭제
├── services/
│   ├── extractor.py     extract_pdf (PyMuPDF 텍스트) — yt-dlp 등 제거
│   ├── pdf_figures.py   그림+캡션 추출·배치 (liby에서 그대로 복사)
│   ├── summarizer.py    PAPER_PROMPT + 강건 JSON 파싱 + sections/figure 빌드
│   │                    + bridge 호출(내부 2회 재시도)
│   ├── bridge_client.py bridge HTTP 클라이언트 (복사)
│   ├── storage.py       save_note/list_notes/get_note/delete_note (최소)
│   └── task_queue.py    인메모리 비동기 워커 + HTMX 폴링 (최소)
├── templates/
│   ├── base.html, index.html
│   └── partials/ (note_list, note_card, note_detail_modal), read.html
├── bridge/            agent-runner-bridge 복사 (claude CLI 게이트웨이)
├── Dockerfile         python:3.13-slim + PyMuPDF (ffmpeg·yt-dlp·discord·anthropic 불필요)
├── docker-compose.yml liby-mini + bridge
├── requirements.txt
├── .env.example
└── README.md
```

### summarizer.py — 의존성 분리
liby의 `claude.py`는 PAPER_PROMPT·`_parse_json`·`_build_sections` 등이 `anthropic`
SDK import와 섞여 있다. mini는 anthropic이 불필요하므로 **순수 부분만 summarizer.py로
복사**한다(프롬프트 + 파싱 + 섹션/문단/figure 빌더 + bridge 호출). 다중 provider
추상화(base/fallback/openai)는 두지 않는다(YAGNI).

## 5. 데이터 흐름

1. 사용자가 웹 UI에서 PDF 업로드(`POST /api/pdf`).
2. 워커가 임시파일로 저장 → `extract_pdf`로 텍스트 추출 → `pdf_figures.extract_figures`로
   본문 그림+캡션을 `vault/pdf/<slug>/figN.<ext>`에 저장.
3. `summarizer.summarize_paper(text, figures_manifest)`:
   - PAPER_PROMPT(5섹션: 목적/실험/이론/결과/생각해볼 점 + 그림 배치)로 bridge 호출.
   - 빈/깨진 응답이면 내부 2회 재시도, 끝내 실패면 명확한 에러.
   - JSON 파싱은 강건 버전(앞뒤 산문·복수객체에서 가장 풍부한 객체 선택).
4. LLM이 배치한 `figure: N`을 실제 이미지(`image:{file,caption}`)로 치환,
   미배치분은 "주요 그림" 갤러리 섹션으로 첨부.
5. SQLite items에 저장. 노트는 DB에, 그림 파일만 `vault/pdf/`에.
6. 목록/검색/모달/전체화면(read)에서 5섹션 + 인라인 그림으로 열람.

## 6. 데이터 모델 (items, 최소)

컬럼: `id, type('pdf'), title, source_url(파일명), summary, sections(JSON),
tags(JSON), topic, summary_mode('detailed'), insights(JSON), questions_raised(JSON),
paragraphs(JSON), created_at`.
- 제거: timeline, transcript_segments, project_id, ai_provider/ai_models,
  api_cost_usd, md_file_path(.md 미사용).

## 7. 화면

- **index**: 상단 PDF 업로드 폼(파일 선택 + 분석 버튼) + 진행 카드(HTMX 폴링) +
  노트 목록 + 제목/태그 검색창.
- **노트 카드**: 제목·태그·요약 일부 + 삭제 + 상세 열기.
- **상세 모달**: 5섹션(목차 + 계층 본문) + 인라인 그림, 삭제·전체화면 버튼.
- **전체화면 read**: 단일 컬럼(영상/트랜스크립트 없음) + 인라인 그림.
- liby의 녹색 테마·다크모드 토글 유지.

## 8. 제외 항목 (YAGNI)

YouTube/text/code/markdown 입력, Discord 봇, 프로젝트, 타임라인/챕터/트랜스크립트,
비용 대시보드, .md vault 내보내기, 다중 AI provider, API 키 경로.

## 9. 검증 기준

- `pytest`: summarizer 파싱(강건성·빈응답 가드), pdf_figures 로직, 라우트(pdf/items)
  단위 테스트. 외부 호출(bridge)은 모킹.
- `docker compose config -q` 유효, `docker build` 성공.
- 실제 논문 PDF로 end-to-end: 5섹션 생성 + 그림 인라인 + 목록/검색/삭제 동작.
- 신규 파일 PII/시크릿 스캔 0건, creds/.env 미추적.

## 10. 범위 제외(다음 단계)

실제 회사 환경에서의 Bedrock 자격증명 확정·검증(로컬에서 옮긴 뒤 적용), GitHub
공개/CI, 멀티유저.
