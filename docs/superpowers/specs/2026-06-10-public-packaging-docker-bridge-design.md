# liby 공개 패키징 — Docker + bridge 통합 + 영문 README 설계 스펙

**작성일**: 2026-06-10
**상태**: 승인됨

---

## 1. 목적

liby를 다른 사람이 받아서 바로 쓸 수 있는 오픈소스로 패키징한다.

- `docker compose up` 한 번으로 liby 앱 + agent-runner-bridge(구독 인증 게이트웨이)가 함께 기동
- 각 사용자가 **자기 구독 계정**(Claude Pro/Max, ChatGPT Plus)으로 분석 가능 — 인증 정보는 저장소·이미지에 포함되지 않고 사용자 로컬에서 주입
- 영문 README 메인 + 한국어 README 보조, UI 스크린샷 포함

## 2. 저장소 구조

```
liby/  (루트 — 기존 앱 코드 위치 불변)
├── bridge/                  ← agent-runner-bridge의 git 추적 파일 23개만 복사
│   ├── src/ test/ scripts/
│   ├── Dockerfile, docker-compose*.yml (단독 실행용 그대로 유지)
│   ├── package.json, package-lock.json, tsconfig.json
│   ├── README.md, .env.example, .gitignore, .dockerignore
│   └── scripts/sync-creds.sh   ← 신규 (macOS/Linux용, ps1과 동등 동작)
├── Dockerfile               ← liby 앱용 (신규)
├── docker-compose.yml       ← 루트: liby + bridge 동시 기동 (신규)
├── .dockerignore            ← 신규
├── README.md                ← 영문으로 교체
├── README.ko.md             ← 현 한국어 README 이동 + Docker 섹션 추가
└── docs/images/             ← 데모 스크린샷
```

- bridge는 git 히스토리 없이 **파일만** 복사한다 (원본 repo: `agent-runner-bridge`).
- 제외: `node_modules/`, `dist/`, `creds/`, `.env`, `workspace/`.
- bridge는 자체 package.json·README를 유지해 나중에 별도 저장소로 분리하기 쉽게 한다.
- 루트 `.gitignore`에 추가: `bridge/node_modules/`, `bridge/dist/`, `bridge/creds/`, `bridge/.env`, `bridge/workspace/`, `data/`.

## 3. Docker 구성

### liby Dockerfile
- 베이스 `python:3.13-slim`, apt로 `ffmpeg` 설치(챕터 스크린샷용 — 없으면 해당 기능만 강등되지만 이미지는 완전체로 제공)
- `pip install -r requirements.txt`, 비루트 사용자 실행
- CMD `uvicorn main:app --host 0.0.0.0 --port 8000`

### 루트 docker-compose.yml
- `liby` 서비스: build `.`, 포트 `8000:8000`, 볼륨 `./data:/data`,
  환경 `DB_PATH=/data/liby.db`, `VAULT_PATH=/data/vault`, `BRIDGE_BASE_URL=http://bridge:8787`,
  `env_file: .env`(optional), 헬스체크 `GET /`
- `bridge` 서비스: build `./bridge`, 내부 포트 8787,
  `BRIDGE_TOKEN`은 루트 `.env` 하나에서 양쪽 서비스에 주입,
  creds 마운트: `./bridge/creds/claude → /home/node/.claude`, `./bridge/creds/codex → /home/node/.codex`(디렉토리 없으면 빈 마운트 — 무해),
  workspace 볼륨 마운트
- API 키만 쓰는 사용자는 `docker compose up liby` 단독 실행 가능

### 구독 인증 플로우 (사용자별 자기 계정)
1. 호스트에서 `claude`/`codex` CLI 로그인 (OAuth는 호스트 전용)
2. `bridge/scripts/sync-creds.ps1`(Windows) 또는 `sync-creds.sh`(macOS/Linux) 실행 → `bridge/creds/`로 복사 (gitignore)
3. `docker compose up` → bridge가 본인 구독으로 CLI 실행
4. 토큰 갱신 시 sync-creds 재실행 필요 (README 명시)
5. README에 "본인 계정으로만 사용" 안내 한 줄

## 4. README

- `README.md`(영문): 한 줄 소개 + 스크린샷 + CI/라이선스 뱃지 → Features → Quick Start
  (① API 키 모드: 단독 컨테이너 ② 구독 모드: compose 전체 + sync-creds) → Configuration 표 →
  Architecture → 제약 안내(UI·요약 출력이 한국어 중심) → 한국어 README 링크
- `README.ko.md`: 현 한국어 README 이동 + Docker/구독 모드 섹션 동기화

## 5. 스크린샷 (개인정보 안전 절차)

- 실 DB(`liby.db`)는 **절대 사용하지 않는다**
- `DB_PATH=./demo.db VAULT_PATH=./demo-vault`로 임시 인스턴스 기동, 가짜 데모 노트 2–3개 삽입
- Playwright로 라이트/다크 캡처 → `docs/images/` 저장 → 데모 DB·vault 폐기

## 6. CI

기존 pytest 잡 유지 + 추가:
- `docker build` 검증(이미지 빌드만, publish 없음)
- bridge 잡: `npm ci && npm run typecheck && npm test` (Node 20)

## 7. 검증 기준

- `pytest` 266개 통과(코드 무변경)
- bridge vitest 통과
- `docker compose up` 후 `GET /` 200, 입력 탭 렌더 확인
- 신규 추적 파일 PII 스캔(이메일·사용자명·토큰) 0건
- `git ls-files`에 creds/.env류 미포함 확인

## 8. 범위 제외 (다음 라운드)

- GHCR 이미지 자동 배포, CONTRIBUTING/뱃지 일부, UI 다국어화, RAG/검색, 웹 아티클 입력, 백업 자동화
