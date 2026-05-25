# 폴더/프로젝트 모드 설계

**작성일:** 2026-05-25

## 개요 (Overview)

liby는 현재 노트를 AI가 자동 부여하는 `topic`(의미 분류)으로만 그룹화한다.
이 기능은 사용자가 **수동으로 관리하는 별도의 조직 축인 "프로젝트(폴더)"**를 추가한다.
topic(자동, 의미적)과 project(수동, 의도적)는 서로 독립적인 두 렌즈로 공존한다.

**목표:** 사이드바에서 "주제별 ↔ 프로젝트별" 모드를 전환하고, 노트를 사용자가 만든 프로젝트에 배정·재배정할 수 있게 한다.

## 핵심 결정 사항 (확정됨)

- **관계:** 프로젝트는 topic과 **병렬인 수동 축**. 한 노트는 topic도 갖고 project에도 속할 수 있다.
- **소속 개수:** 한 노트는 **하나의 프로젝트에만** 속한다 (폴더 비유). `NULL` = 미분류.
- **배정:** **둘 다** — 입력 시 현재 프로젝트 선택 + 생성 후 노트 카드에서 재배정.
- **vault 구조:** vault는 지금처럼 **type별 폴더 유지**. 프로젝트는 DB 필드 + .md frontmatter `project:` 태그로만 관리 (실제 파일 이동 없음).
- **사이드바:** 상단 **모드 토글** `[주제별 | 프로젝트별]`. 기본은 주제별(기존 동작 보존).
- **프로젝트 관리:** 생성(create), 이름 변경(rename), 삭제(delete) 모두 지원.

## 데이터 모델

### 신규 테이블: `projects`
```sql
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```
- 노트가 없는 **빈 프로젝트도 존재 가능**하게 별도 테이블로 관리.
- `name`은 UNIQUE (중복 프로젝트명 방지).

### `items` 컬럼 추가
- `project_id INTEGER` (nullable, `projects.id` 참조). `NULL` = 미분류.
- 정규화된 ID 참조 → 이름 변경 시 `projects` 한 행만 수정하면 됨.

### 마이그레이션 (`models.py` `init_db`)
- `CREATE TABLE IF NOT EXISTS projects ...` 추가.
- `items.project_id`는 `CREATE TABLE IF NOT EXISTS`로는 기존 DB에 안 생기므로:
  - `PRAGMA table_info(items)`로 `project_id` 존재 여부 확인.
  - 없으면 `ALTER TABLE items ADD COLUMN project_id INTEGER`.
- 기존 노트는 전부 `project_id = NULL` (미분류)로 시작.

## 컴포넌트

### 1. 사이드바 모드 토글
- 사이드바 상단에 세그먼트 토글 `[주제별 | 프로젝트별]`.
- 기본 모드: **주제별** (기존 `#topic-list` 동작 그대로).
- **프로젝트별 모드** 목록 구성: `전체 노트` → 프로젝트 목록(이름 + 노트 개수) → `미분류`(개수) → `+ 새 프로젝트` 버튼.
- 모드 전환은 클라이언트 JS 상태. 사이드바 목록 영역을 HTMX로 교체:
  - 주제별: `GET /api/items/topics` (기존)
  - 프로젝트별: `GET /api/projects` (신규, 사이드바 partial 반환)
- 프로젝트 클릭 시 동작은 topic 클릭과 동일: 해당 프로젝트 노트만 로드, "오늘의 추천 노트" 섹션 숨김, 섹션 라벨을 프로젝트명으로 변경, "전체 노트" 활성 해제. (기존 `enterTopicView` 패턴 재사용 → `enterProjectView(id, name)`)
- "미분류" 클릭 → `project_id=none` 필터.

### 2. 프로젝트 관리 (생성/이름변경/삭제)
- **생성:** `+ 새 프로젝트` → `prompt()`로 이름 입력 → `POST /api/projects` (form: `name`) → 프로젝트 목록 갱신. 이름 중복 시 400.
- **이름 변경:** 프로젝트 항목의 작은 ✎ 버튼 → `prompt()` → `PATCH /api/projects/{id}` (form: `name`) → 목록 + (현재 보고 있으면) 라벨 갱신. `projects.name` 한 행 수정. 해당 프로젝트 노트들의 .md frontmatter `project:`도 일괄 재작성.
- **삭제:** 프로젝트 항목의 작은 ✕ 버튼 → 확인 → `DELETE /api/projects/{id}` → 소속 노트는 `project_id=NULL`(미분류)로, 해당 노트들의 frontmatter `project:` 제거. `projects` 행 삭제.

### 3. 입력 시 배정 (공유 드롭다운)
- **전 탭 공유** `현재 프로젝트 ▼` 셀렉트(`id="current-project"`, 기본값 `(없음)`).
- **배치:** 탭 전환 시 `#input-panel` 내부가 통째로 교체되므로, 셀렉트는 **`#input-panel` 밖**(예: 입력 패널 우측 또는 바로 위의 얇은 영역)에 두어 탭을 바꿔도 선택이 유지되게 한다.
- **폼 제출 시 포함:** 각 입력 폼(YouTube/PDF/Code/Text)에 `hx-include="#current-project"`를 추가 → 폼이 자기 필드 + 공유 셀렉트의 `project_id`를 함께 전송. (HTMX `hx-include`로 폼 외부 요소 값을 포함 — JS 동기화 불필요)
- 셀렉트는 프로젝트 목록으로 채움. 프로젝트 생성/삭제 후 이 셀렉트도 갱신(HTMX 또는 이벤트로 재로드).
- 라우터(youtube/pdf/code/text)는 `project_id: Optional[int] = Form(None)`를 받아 `save_note`에 전달.

### 4. 생성 후 재배정
- 노트 카드(`note_card.html`)에 작은 `프로젝트 ▼` 셀렉트(현재 배정 표시, 옵션: 미분류 + 전체 프로젝트).
- 변경 시 `POST /api/items/{id}/project` (form: `project_id`, 빈 값=미분류) → `items.project_id` 갱신 + 해당 .md frontmatter `project:` 재작성.

### 5. .md frontmatter
- `_make_md_content`에 `project: {프로젝트명 또는 빈값}` 줄 추가.
- `save_note`는 `project_id` → 이름 조회 후 frontmatter에 기록.
- 재배정/이름변경/삭제 시 영향받는 노트의 .md frontmatter `project:` 줄을 재작성 (파일 전체 재생성이 가장 단순; 기존 데이터는 DB에서 읽어 재구성).

### 6. 저장/조회 계층 (`storage.py`)
- `save_note(...)`에 `project_id: int | None = None` 파라미터 추가 → INSERT에 포함.
- `list_notes(...)`에 `project_id` 필터 추가:
  - 정수면 `AND project_id = ?`
  - 문자열 `"none"`이면 `AND project_id IS NULL`
- 신규 함수:
  - `list_projects(db_path)` → `[{id, name, count}]` (각 프로젝트 노트 수 + 미분류 수). 사이드바용.
  - `create_project(db_path, name)`, `rename_project(db_path, id, name)`, `delete_project(db_path, id)`.
  - `set_note_project(db_path, note_id, project_id)`.
  - 이름변경/삭제/재배정 후 영향 노트 .md frontmatter 재작성 헬퍼.

### 7. API 엔드포인트 (신규)
신규 라우터 `routers/projects.py` (`prefix="/api/projects"`):
- `GET /api/projects` → 사이드바 프로젝트 목록 partial (`partials/sidebar_projects.html`).
- `POST /api/projects` (form: name) → 목록 partial.
- `PATCH /api/projects/{id}` (form: name) → 목록 partial.
- `DELETE /api/projects/{id}` → 목록 partial.

`routers/items.py`:
- `GET /api/items`에 `project_id` 쿼리 파라미터 추가 (필터).
- `POST /api/items/{id}/project` (form: project_id) → 갱신된 `note_card.html` 반환.

`main.py`: `projects` 라우터 등록.

## 데이터 흐름 예시

1. 사용자가 `+ 새 프로젝트` → "회사 리서치" 생성 → `projects`에 행 추가.
2. 입력 패널에서 `현재 프로젝트: 회사 리서치` 선택 → YouTube URL 분석 → 노트가 `project_id=회사리서치`로 저장, .md에 `project: 회사 리서치`.
3. 사이드바 `프로젝트별` 토글 → `회사 리서치 (1)` 클릭 → 해당 노트만 표시.
4. 다른 노트의 카드에서 `프로젝트 ▼ → 회사 리서치` 선택 → 재배정 + frontmatter 갱신.

## 비목표 (Non-goals)

- 한 노트의 다중 프로젝트 소속 (단일 소속만).
- vault 디렉토리의 실제 프로젝트 폴더 분리 (type별 유지).
- 프로젝트 중첩(하위 프로젝트)/계층 구조.
- 프로젝트별 색상/아이콘 커스터마이즈.

## 테스트 고려사항

- 마이그레이션: 기존 DB(컬럼 없음)에서 `project_id` 추가가 멱등하게 동작하는지.
- 프로젝트 CRUD: 생성/중복방지/이름변경/삭제 시 노트 미분류 처리.
- 재배정 시 DB와 .md frontmatter가 일치하는지.
- 필터: `project_id=N`, `project_id=none`, 미지정(전체) 각각.
- 사이드바 모드 전환이 기존 주제별 동작을 깨지 않는지.
- 빈 프로젝트가 목록에 개수 0으로 표시되는지.
