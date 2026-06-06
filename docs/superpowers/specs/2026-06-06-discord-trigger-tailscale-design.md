# Discord 트리거 + Tailscale 열람 — 외부 분석/열람 (공개 노출 0)

작성일: 2026-06-06

## 배경 / 문제

liby는 집 PC의 Docker bridge(Claude/Codex CLI, 구독 사용)에서만 분석이 가능하다.
분석 연산을 클라우드로 옮길 수 없으므로, "외부에서 사용"은 결국 *밖에서 → 집 PC의
liby로* 신호를 보내고 결과를 받는 구조가 된다.

Cloudflare 같은 퍼블릭 터널은 사실상 개인 볼트를 인터넷에 공개 배포하는 것이라
인증·노출 부담이 크다. 대신 **공개 노출이 전혀 없는** 두 경로를 결합한다.

- **Discord 봇**: 폰에서 유튜브 링크/텍스트를 던지면 분석 → 요약을 Discord로 회신.
  봇은 아웃바운드 연결만 하므로 인바운드 포트·터널·공개 IP가 불필요.
- **Tailscale 사설망**: 전체 노트(read.html)를 *내 기기에서만* 열람. 인터넷 공개 아님.

## 목표

1. 외부(폰)에서 Discord로 유튜브 링크/텍스트를 던지면 분석이 트리거된다.
2. 분석 결과 요약을 Discord 임베드로 회신한다(제목·요약·핵심·챕터 타임스탬프·태그).
3. 전체 노트는 Tailscale 사설망을 통해 기존 웹 UI 그대로 열람한다.
4. 공개 인터넷 노출이 0이다. 집 PC가 켜져 있고 `uvicorn` 한 번이면 전부 동작한다.

## 비목표 (V1)

- PDF·코드 **파일 첨부** 분석 (유튜브 링크 + 텍스트만).
- 공개 인터넷 노출 / Cloudflare 퍼블릭 터널.
- 다중 사용자 / 노트 공유.
- Discord에서 취소·재분석, 슬래시 커맨드 등록 UI, 버튼 인터랙션.
- 외부 API(Anthropic/OpenAI) 잔액 조회.

## 전체 흐름

```
폰(밖)                     집 PC (켜져만 있으면 됨)
 │  ① 유튜브 링크 DM        ┌─────────────────────────────┐
 ├────────────────────────▶│ Discord 봇 (아웃바운드 연결)  │
 │                          │   └ 내 ID만 응답              │
 │  ④ 임베드+요약+링크 ◀────│        │ ② localhost 호출      │
 │                          │        ▼                      │
 │                          │ liby FastAPI + 기존 task 큐   │
 │                          │   └ Docker bridge(CLI 분석)   │
 │  ⑤ "전체 노트" 링크       │        │ ③ 완료              │
 ├── Tailscale(사설망) ────▶│  read.html (내 기기만 접근)   │
 └────────────────────────▶└─────────────────────────────┘
```

분석은 **기존 task 큐·builder를 그대로 재사용**한다. 새 분석 로직은 없다.

## 구성 요소

작고 독립적인 단위로 나눈다. 각 단위는 하나의 책임을 가지며 독립 테스트 가능하다.

### A. 봇 전용 JSON API — `routers/bot.py` (`/api/bot/*`)

봇이 HTML을 스크레이핑하지 않도록 JSON을 제공. 내부적으로 기존
`new_task`/`enqueue`/`get_task`와 storage를 재사용한다.

- `POST /api/bot/analyze`
  - 입력: `{input: str, mode?: "quick"|"detailed", project_id?: int}`.
  - 입력 판별: 유튜브 URL이면 `youtube` source, 아니면 `text` source. 판별은 기존
    `_extract_video_id`/유튜브 정규식 재사용.
  - 동작: 적절한 spec을 만들어 `new_task(source_type, title, spec) + enqueue(task)`
    (coro_fn 생략 → 등록된 builder가 재구성 → 영구화·재시도 적용).
  - 출력: `{task_id, title, kind}` (`kind` ∈ `youtube`|`text`).

  > **선행 작업(포함된 개선):** 현재 `routers/text.py`는 youtube와 달리 builder
  > 미등록(inline `coro_fn` 클로저)이라 영구화·재시도가 안 되고 봇 API가 일관되게
  > 못 쓴다. youtube에 이미 적용된 패턴 그대로 `routers/text.py`를 builder로
  > 리팩터(`_build_text_do_work(spec)` + `register_builder("text", ...)`, POST
  > 핸들러는 spec 만들어 `enqueue(task)`)한다. 이로써 봇·웹 양쪽 text 분석이 모두
  > 영구화·재시도를 얻는다. 범위를 벗어난 리팩터는 하지 않는다.
- `GET /api/bot/tasks/{task_id}` → `{status, note_id, error, title}` (`get_task` 기반).
- `GET /api/bot/notes/{note_id}` → 임베드용 슬림 JSON
  `{title, summary, insights, chapters: [{t, label}], tags, read_url}`.
  - `read_url = f"{PUBLIC_BASE_URL}/api/items/{note_id}/read"`.
  - `chapters`는 노트의 chapter 데이터에서 `{t(초), label}`만 추출.
- 보안: 가벼운 `X-Bot-Token` 헤더 가드(`BOT_API_TOKEN`이 설정된 경우에만 강제).
  localhost/타이넷 내부용. 미설정 시 가드 생략(개발 편의).

### B. Discord 봇 — `services/discord_bot.py`

- `discord.py` 사용. `DISCORD_BOT_TOKEN`이 설정된 경우에만 **`main.py` lifespan에서
  `asyncio.create_task`로 기동**한다. → `uvicorn` 한 번이면 서버+워커+봇 전부 켜짐.
  토큰 미설정 시 봇은 조용히 비활성(기존 동작에 영향 없음).
- 권한: `DISCORD_ALLOWED_USER_ID`와 일치하는 작성자의 메시지에만 반응. 그 외 무시.
- 처리:
  1. 허용된 사용자의 메시지 수신(DM 또는 허용 채널).
  2. ⏳ 반응 또는 "분석 시작…" 회신.
  3. 메시지에 "상세"/"detailed" 포함 시 `mode=detailed`, 기본 `quick`.
  4. `POST /api/bot/analyze` → `task_id`.
  5. `GET /api/bot/tasks/{id}`를 ~2초 간격으로 폴링(상한 시간 내).
  6. `done` → `GET /api/bot/notes/{id}` → `build_embed`로 임베드 작성해 회신.
     `error` → 에러 메시지. 폴링 타임아웃 → task id와 함께 안내.
- 봇은 자신의 메시지/타 사용자 메시지에는 반응하지 않는다(루프 방지).

### C. 결과 포맷터 — `services/discord_format.py`

- 순수 함수 `build_embed(note: dict) -> discord.Embed` (또는 dict 표현). Discord
  연결 없이 단위 테스트 가능하도록 입력은 평범한 dict.
- 챕터는 **네이티브 유튜브 타임스탬프 링크**로:
  `[{mm:ss} {label}](https://youtu.be/{VIDEO_ID}?t={seconds})`.
  → 폰 유튜브 앱에서 해당 지점으로 점프(앱 웹 UI 불필요).
- 임베드 필드: 제목, 요약(길이 truncation), 핵심 인사이트(최대 5개), 챕터(최대 8개),
  태그, 하단에 "📖 전체 노트" `read_url` 링크.
- Discord 임베드 길이 한도(설명 4096, 필드값 1024 등)를 고려해 안전하게 자른다.

### D. Tailscale (코드 아님 — 운영 문서)

`docs/` 또는 README에 설치 절차 기록:
1. PC와 폰에 Tailscale 설치, 동일 계정으로 `tailscale up`.
2. `uvicorn`을 `--host 0.0.0.0`으로 바인딩(타이넷+LAN에서만 도달, 공개 아님).
3. PC의 MagicDNS 이름 확인 후 `.env`의 `PUBLIC_BASE_URL`에 설정
   (예: `http://<pc-name>.<tailnet>.ts.net:8000`).
4. 폰에서 Tailscale 켜고 `read_url` 클릭 → 기존 웹 UI 그대로 열람.

## 설정 (`config.py` / `.env`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_BOT_TOKEN` | `""` | 비어 있으면 봇 비활성 |
| `DISCORD_ALLOWED_USER_ID` | `""` | 이 ID의 메시지에만 반응(int) |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | read_url 생성 베이스(Tailscale 이름) |
| `BOT_API_TOKEN` | `""` | 설정 시 `/api/bot/*`에 `X-Bot-Token` 강제 |

`requirements.txt`에 `discord.py` 추가.

## "쉽게 서버 열기"

봇이 in-process이므로 단일 명령으로 서버+워커+봇이 함께 뜬다:

```
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

선택: 위 명령을 담은 `start.ps1` 추가 + (원하면) Windows 시작 시 자동 실행 등록을
문서화. PC 재부팅 후에도 외부에서 바로 사용 가능.

## 에러 처리

- 봇: 인식 못 한 입력 → 사용법 안내. 분석 실패 → 에러 노출. bridge 예산초과/타임아웃
  → 친절한 메시지. 폴링 타임아웃 → task id와 함께 안내.
- API: task/note 없음 → 404. 미지원 입력 → 400. `BOT_API_TOKEN` 불일치 → 401.

## 테스트

- `discord_format` 순수 함수: 임베드 필드 구성, 타임스탬프(초→mm:ss·`?t=`) 변환,
  길이 truncation, 챕터 없는 노트 처리.
- `/api/bot/*` 라우트: 기존 테스트 패턴처럼 build를 mock하고 ASGI httpx로
  analyze→task_id, task 상태 JSON, note JSON(read_url 포함) 검증.
- 입력 판별 단위 테스트: 유튜브 URL(일반/`live/`/`embed/`/`youtu.be`) vs 일반 텍스트.
- 봇 메시지 핸들러 디스패치: 가짜 message 객체로 (a) 허용 ID만 통과,
  (b) 타 사용자/봇 자신 무시, (c) analyze 호출됨을 검증(discord client mock).

## 검증 (수동)

1. `.env`에 `DISCORD_BOT_TOKEN`/`DISCORD_ALLOWED_USER_ID` 설정 후 서버 기동 → 로그에
   봇 로그인 확인.
2. 폰 Discord에서 봇에게 유튜브 링크 DM → ⏳ → 잠시 후 요약 임베드 수신.
3. 임베드의 챕터 타임스탬프 탭 → 폰 유튜브 앱이 해당 지점으로 점프.
4. 임베드의 "전체 노트" 링크 탭(Tailscale on) → 브라우저에서 read.html 정상 열람.
5. "상세" 포함 메시지 → detailed 모드로 분석됨.
6. 허용되지 않은 계정으로 시도 → 봇 무반응.

## 분량 / 사이즈

- 신규 4 파일: `routers/bot.py`, `services/discord_bot.py`,
  `services/discord_format.py`, 운영 문서(README/docs 추가).
- 수정 4 파일: `config.py`, `main.py`(lifespan에 봇 기동), `requirements.txt`,
  `routers/text.py`(builder 패턴으로 리팩터).
- 테스트 ~5개 파일(text builder 리팩터 회귀 포함). Subagent-Driven 또는 inline 모두
  가능한 중간 사이즈.
