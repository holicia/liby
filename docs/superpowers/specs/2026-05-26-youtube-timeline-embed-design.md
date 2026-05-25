# YouTube 타임라인 + 임베드 설계

**작성일:** 2026-05-26

## 개요 (Overview)

liby의 YouTube 노트에 **영상 임베드**와 **챕터 타임라인**을 추가한다.
노트 상세 모달("전체 보기")에서 영상을 바로 재생하고, AI(또는 영상 자체의 네이티브) 챕터 목록을 클릭해 해당 지점으로 이동할 수 있다.

**목표:** YouTube 노트를 열면 영상을 임베드해 보여주고, "0:00 인트로 / 2:30 핵심 개념..." 형태의 챕터 타임라인을 제공하며, 챕터 클릭 시 임베드 영상이 그 시점으로 부드럽게 이동한다.

## 핵심 결정 사항 (확정됨)

- **타임라인 형태:** AI 챕터 요약 (타임스탬프 + 짧은 라벨 목록).
- **챕터 생성 전략:** **하이브리드** — 영상에 제작자 네이티브 챕터가 있으면 그대로 사용(무료·정확), 없으면 AI로 생성.
- **표시 위치:** 기존 상세 모달(`note_detail_modal.html`) 확장. 상단에 영상 임베드 + 챕터 목록, 그 아래 기존 요약·포인트.
- **이동 방식:** YouTube **IFrame Player API** (`player.seekTo`)로 재로딩 없이 부드럽게 이동.
- **범위:** 신규 YouTube 노트는 분석 시 챕터 자동 생성. 기존 노트는 모달의 "타임라인 생성" 버튼으로 온디맨드 백필. **임베드 영상은 모든 YouTube 노트에 즉시 적용**(video_id는 source_url에서 추출).

## 데이터 모델

### `items.timeline` 컬럼 신설
- `timeline TEXT` (JSON, nullable). 형식: `[{"t": 초(int), "label": "챕터 제목"}]`. NULL/빈 배열 = 챕터 없음.
- 마이그레이션(`models.py`): `project_id`와 동일 패턴 — `PRAGMA table_info(items)`로 존재 확인 후 없으면 `ALTER TABLE items ADD COLUMN timeline TEXT`.
- **video_id는 저장하지 않음** — 렌더 시점에 `source_url`에서 정규식으로 추출.

## 컴포넌트

### 1. 추출 계층 (`services/extractor.py`)
- yt-dlp `extract_info` **단일 호출**로 다음을 모두 반환하는 함수 추가 (예: `extract_youtube_full(url) -> dict`):
  - `text`: join된 자막 텍스트 (요약용, 기존과 동일)
  - `video_id`
  - `native_chapters`: `info.get("chapters")`가 있으면 `[{"t": int(start_time), "label": title}]`로 정규화, 없으면 `None`
  - `segments`: json3 이벤트의 `tStartMs`를 보존한 타임스탬프 자막 `[{"t": 초, "text": ...}]` (AI 폴백용)
- 기존 `extract_youtube(url) -> (text, video_id)`는 유지하거나, youtube 라우터를 `extract_youtube_full`로 전환(다른 타입에는 영향 없음).
- video_id 추출 헬퍼 `_extract_video_id`는 이미 존재(재사용).

### 2. 챕터 생성 (`services/`, 하이브리드)
- 함수 `resolve_chapters(native_chapters, segments, ai) -> (list[{t,label}], cost_usd, model)`:
  - `native_chapters`가 있으면 그대로 반환 (비용 0).
  - 없으면 `ai.generate_chapters(timestamped_transcript)` 호출.
- AI 메서드 `generate_chapters(timestamped_transcript: str) -> tuple[list[dict], float, str]`를 `AIProvider`(claude, openai)에 추가. 반환: `(chapters, cost_usd, model)` — `resolve_chapters`와 동일한 튜플 형태.
  - 입력: 타임스탬프가 붙은 자막 텍스트(예: 각 줄 `[mm:ss] 문장`).
  - AI 응답 JSON: `{"chapters": [{"t": 초, "label": "짧은 제목"}]}` (기존 summarize의 JSON 파싱 패턴 재사용). 5~12개 챕터, 시간 오름차순. cost_usd/model은 호출 메타에서 채움.
- `segments`에서 타임스탬프 자막 문자열을 만드는 헬퍼 포함.

### 3. 저장 (`services/storage.py`)
- `save_note(..., timeline: list | None = None)` — `timeline`을 JSON으로 INSERT(`items.timeline`). 다른 타입은 None.
- `set_timeline(db_path, note_id, chapters: list)` — 온디맨드 백필용 UPDATE.
- `get_note`/`list_notes`는 `SELECT *`이므로 `timeline`이 자동 포함됨. `_parse_row`의 `_JSON_FIELDS`에 `"timeline"` 추가해 자동 역직렬화.

### 4. API (`routers/items.py`)
- `GET /api/items/{id}/detail` 수정: youtube 노트면 `source_url`에서 `video_id`를 추출해 컨텍스트에 `video_id`, `timeline`을 함께 전달. (비youtube/추출 실패 시 `video_id=None`.)
- **신규** `POST /api/items/{id}/timeline`: 기존 노트 온디맨드 백필.
  - 노트 로드 → `source_url`에서 `extract_youtube_full` 재추출 → `resolve_chapters` → `set_timeline` → 비용 기록(AI 사용 시) → 재렌더된 `note_detail_modal.html` 반환.

### 5. 신규 분석 흐름 (`routers/youtube.py`)
- `do_work`: `extract_youtube_full(url)`로 text+video_id+native_chapters+segments 획득 → `summarize(text)` → `resolve_chapters(...)` → `save_note(..., timeline=chapters)` → AI 챕터 비용은 `record_api_cost`로 추가 기록.

### 6. 모달 UI (`templates/partials/note_detail_modal.html`)
- 헤더 아래, 요약 위에 영상 섹션 추가:
  - `video_id`가 있으면 `<div id="yt-player" data-video-id="{{ video_id }}"></div>` 플레이스홀더.
  - `timeline`이 있으면 챕터 목록: 각 항목 `M:SS  라벨`, 클릭 시 `ytSeek({{ t }})`.
  - youtube인데 `timeline`이 비어있으면 **"타임라인 생성"** 버튼: `hx-post="/api/items/{{ note.id }}/timeline"`, `hx-target="#note-modal"`, `hx-swap="innerHTML"`.
- IFrame Player API 스크립트(모달 내 또는 base.html):
  - `https://www.youtube.com/iframe_api`를 1회 로드(중복 가드).
  - 모달이 주입될 때 `#yt-player`의 `data-video-id`로 `YT.Player` 생성.
  - 전역 `ytSeek(sec)` → `player.seekTo(sec, true); player.playVideo();`.
  - 모달이 HTMX로 매번 새로 주입되므로, 주입 시마다 플레이어를 (재)초기화하고 닫을 때 정리.

### 7. 비용 기록
- AI 챕터 생성(폴백)만 비용 발생 → `record_api_cost`로 노트에 귀속. 네이티브 챕터는 비용 0.

## 데이터 흐름 예시

1. 신규 youtube 분석: 확장 추출 → 요약 저장 → 네이티브 챕터 있으면 사용 / 없으면 AI 생성 → `timeline` 저장.
2. 상세 모달 열기: `video_id` + `timeline` 전달 → 임베드 + 챕터 렌더.
3. 챕터 클릭 → `ytSeek(t)` → 플레이어가 해당 지점으로 이동.
4. 기존 노트(타임라인 없음): "타임라인 생성" 클릭 → 재추출 + 챕터 → 저장 → 모달 재렌더(챕터 표시).

## 비목표 (Non-goals)

- 자막 전문 검색/표시, 챕터 수동 편집.
- YouTube 외 소스(PDF/Code/Text) 임베드.
- 영상 다운로드/오프라인 저장.
- 자동 백필(기존 전체 일괄) — 온디맨드만.

## 테스트 고려사항

- 추출: 네이티브 챕터 파싱(`info['chapters']` mock), 세그먼트 타임스탬프 빌드, 챕터 없는 영상.
- 하이브리드 선택: 네이티브 있으면 AI 미호출, 없으면 AI 호출.
- AI `generate_chapters`: JSON 파싱(시간 오름차순, 라벨), mock 응답.
- storage: `timeline` 저장/조회, `set_timeline`, `_parse_row` 역직렬화.
- 마이그레이션: `timeline` 컬럼 멱등 추가.
- 라우터: detail이 youtube에 video_id+timeline 전달 / 비youtube는 video_id 없음 / 백필 엔드포인트가 set_timeline 호출.
- 프론트(IFrame Player, ytSeek, 모달 재초기화): 브라우저 수동 검증.
