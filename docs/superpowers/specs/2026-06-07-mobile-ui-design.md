# liby 모바일 UI 개선 설계

## 배경 / 문제

폰 사용 흐름은 "Discord 전용 채널에 링크 전송 → 요약 임베드 수신 → 임베드의 '전체 노트' 링크로 열람"이다.
Tailscale로 외부 열람은 동작하나, 폰에서 화면이 불편하다.

원인 진단:

1. **`read.html`에 viewport 메타 태그 누락** — 임베드 링크로 여는 노트 전체보기 페이지(`/api/items/{id}/read`)에 `<meta name="viewport">`가 없다. `base.html`에는 있다. 이게 없으면 모바일 브라우저가 데스크톱 폭(980px)으로 렌더링 후 축소해 글씨가 깨알같이 작아진다. 페이지에 이미 `md:grid` 반응형이 있지만 viewport가 없어 동작하지 못한다.
2. **`read.html` 콘텐츠 순서** — DOM이 `영상+트랜스크립트(aside) → 요약/본문(article)` 순이라, 모바일 1단 스택에서 긴 트랜스크립트를 다 지나야 요약이 보인다.
3. **`base.html` 메인 앱이 데스크톱 전용 구조** — 고정 208px 사이드바 + 마우스 전용 리사이저 + `body` `overflow-hidden`. 폰(~390px)에서 사이드바가 화면 절반을 먹고 접을 방법이 없다.

## 목표

폰에서 (a) 노트 전체보기(`read.html`)를 읽기 편하게, (b) 메인 앱(`base.html`)을 햄버거 드로어로 탐색 가능하게.
데스크톱(`md+`) 레이아웃은 **현행 그대로 유지**한다.

## 범위 (surface 3개)

### 1) `read.html` — 노트 전체보기 (폰 주력 화면)

- **viewport 메타 추가** (핵심 한 줄):
  ```html
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ```
- **모바일 콘텐츠 순서 재배치**: 모바일은 `영상 → 요약/본문 → 트랜스크립트`, 데스크톱은 현행 2단(좌: 영상 sticky + 트랜스크립트 / 우: 본문) 유지.
  - 최상위를 `flex flex-col md:grid md:grid-cols-5`로 두고, 영상 / 본문(article) / 트랜스크립트를 형제 블록으로 분리.
  - 모바일: `order` 유틸로 영상(order-1) → 본문(order-2) → 트랜스크립트(order-3).
  - 데스크톱: grid 명시 배치로 좌측 col(영상 + 트랜스크립트) / 우측 col(본문). 영상은 좌측 상단 sticky, 트랜스크립트는 그 아래.
  - 현재 `aside`가 영상 + 트랜스크립트를 함께 품고 있으므로, 트랜스크립트를 형제 블록으로 끌어내 재배치 가능하게 구조를 조정한다.

### 2) `base.html` — 메인 앱 (햄버거 드로어)

- **오프캔버스 드로어**:
  - 모바일(`<md`): `#sidebar`를 `fixed` + 화면 밖(`-translate-x-full`), ☰ 토글 시 왼쪽 슬라이드 인 + 어두운 오버레이.
  - 데스크톱(`md+`): static 사이드바 현행 유지. 리사이저(`#sidebar-resizer`)는 `hidden md:block`(마우스 전용이라 모바일 숨김). 기존 mousedown JS는 요소 존재 가드가 있어 안전.
  - 닫힘 트리거: 오버레이 탭 / 사이드바 항목 선택(전체노트·주제·프로젝트 클릭) / Esc.
- **네비바**:
  - ☰ 햄버거 버튼 추가 (`id="sidebar-toggle"`, `md:hidden`).
  - 입력 탭(YouTube/PDF/Code/Text/Markdown) 행에 `overflow-x-auto`로 좁은 폭 가로 스크롤.
- **입력 패널**: 현행 마크업이 모바일에서 자연 스택만 되게. 접기 등은 비목표.

### 3) `note_detail_modal.html` — 노트 탭 시 모달

- 이미 `w-full max-w-2xl`라 대체로 OK. 모바일 패딩 `p-4 md:p-6`로 축소, 상단 우측 3버튼(🗑/📖/✕)과 제목이 겹치지 않게 헤더 `pr` 여유만 조정. 구조 변경 없음.

## 구현 메모

- **JS (base.html)**: 드로어 토글 함수 추가 — 사이드바 `translate` 클래스와 오버레이 표시 토글. 기존 `enterHomeView`/`enterTopicView`/`enterProjectView`/`enterUnassignedView` 등 사이드바 항목 선택 함수 끝에서 "모바일이면 드로어 닫기" 호출. Esc 핸들러는 기존 keydown 리스너(모달 닫기)에 드로어 닫기를 함께 처리.
- **다크모드**: 새 요소(오버레이, 드로어 상태)도 기존 다크 클래스 패턴(`dark:`)을 따른다.
- 순수 Tailwind 반응형 클래스만 사용. 별도 CSS 프레임워크/모바일 전용 템플릿 도입 없음.

## 테스트 / 검증

### 자동 (기존 `test_routes_partials.py` 문자열 검사 패턴)

- `read.html`: `/api/items/{id}/read` 응답에 `name="viewport"` 포함.
- `read.html`: 모바일 재배치 컨테이너 클래스(`flex flex-col md:grid`) 포함.
- `base.html`: `/` 응답에 햄버거 토글(`id="sidebar-toggle"`)과 드로어 마커(`md:hidden`, `-translate-x-full` 계열) 포함.
- 기존 251개 스위트 전부 통과 유지.

> read.html 자동 테스트는 DB에 노트가 있어야 한다. 기존 read 라우트 테스트가 있으면 그 픽스처 패턴을 재사용하고, 없으면 임시 노트를 넣어 GET 후 단언.

### 수동 (폰 실기기, Tailscale 경유)

1. 임베드 "전체 노트" 링크 → read.html: 글씨 정상 크기, 영상 → 요약 → 트랜스크립트 순.
2. 메인 앱 `/`: ☰로 드로어 열기/닫기, 항목 선택 시 닫힘, 데스크톱 폭에선 기존 그대로.
3. 노트 탭 → 모달이 화면에 꽉 맞게.

## 비목표 (YAGNI)

- 입력 패널 접기 / 모바일 전용 입력 UX
- 하단 탭바, 스와이프 등 제스처 네비
- 데스크톱 레이아웃 변경 (전부 `md+`에서 현행 유지)
- 별도 모바일 전용 템플릿 / CSS 프레임워크

## 분량 / 사이즈

- 수정 3개 파일: `read.html`(viewport + 순서 재배치), `base.html`(드로어 + 네비바 + JS), `note_detail_modal.html`(패딩).
- 테스트: 신규 단언 3~4개.
- 단일 plan, Subagent-Driven 없이 inline 처리 가능한 규모.
