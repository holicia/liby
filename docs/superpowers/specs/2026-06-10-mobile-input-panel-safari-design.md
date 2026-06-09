# liby 모바일 입력 패널 레이아웃 + iOS Safari 입력 최적화

## 배경 / 문제

모바일에서 네비바의 `+ 분석` 토글로 입력 패널을 펼치면, 입력 폼이 **가로폭에 안 맞고 길어진다**(사용자 실기기 관찰, Chrome·Safari 공통).

원인: `templates/partials/input_youtube.html`의 폼이 **줄바꿈 없는 한 줄 가로 배치**다.
```html
<form ... class="flex gap-2 items-center">
  <input name="url" class="flex-1 ...">   <!-- URL -->
  <select name="provider" ...>            <!-- provider -->
  <select name="mode" ...>                <!-- mode -->
  <button type="submit" ...>분석하기</button>
</form>
```
모바일 폭(~358px)에서 URL 입력 + 셀렉트 2개 + 버튼이 한 줄에 안 들어가 가로 오버플로/왜곡이 생긴다. 이는 레이아웃 문제로 **브라우저 무관**(Safari 전용 아님).

추가로, 같은 입력 패널에는 **iOS Safari 고유 이슈**가 있다: 폼 컨트롤 글꼴이 16px 미만이면(URL 14px, select 12px) Safari가 **포커스 시 화면을 자동 확대**한다.

## 목표

(1) 펼친 입력 패널이 모바일 폭에 맞게 세로 정렬되어 가로 오버플로가 없도록. (2) iOS Safari에서 입력 포커스 시 자동 확대가 일어나지 않도록. 데스크톱(`md+`)은 현행 유지.

## 변경 (2곳)

### 1) `templates/partials/input_youtube.html` — 폼 모바일 세로 스택

- 폼: `flex gap-2 items-center` → `flex flex-col md:flex-row gap-2 md:items-center`
- URL 입력: `flex-1` → `md:flex-1`
  - 이유: 모바일 `flex-col`에서 `flex-1`은 교차축이 아니라 **주축(세로)** 으로 늘어나 입력창이 세로로 길어진다. 데스크톱에서만 `flex-1`(가로 신장) 적용.

동작:
- 모바일: `flex-col` + 기본 `align-items: stretch` → URL/provider/mode/버튼이 각각 **전체폭**으로 세로 정렬. 가로 오버플로 없음.
- 데스크톱: `md:flex-row md:items-center` + URL `md:flex-1` → 현행 한 줄 레이아웃 그대로.

```
[모바일 — + 분석 펼침]            [데스크톱 — 현행]
┌──────────────────────┐       ┌───────────────────────────────────┐
│ [ YouTube URL ...    ]│       │ [URL .......] [provider][mode][분석]│
│ [ Claude CLI ▾       ]│       └───────────────────────────────────┘
│ [ 빠른 정리 ▾        ]│
│ [     분석하기       ]│
└──────────────────────┘
```

**범위**: 모바일에서 노출되는 입력은 YouTube뿐이다(입력 타입 탭이 `hidden md:flex`라 모바일 비노출 → pdf/code/text/markdown 입력은 모바일에서 도달 불가). 따라서 나머지 4개 입력 partial은 변경하지 않는다(데스크톱에서만 노출되며 거기선 한 줄이 들어감). YAGNI.

### 2) `templates/base.html` `<style>` — iOS 자동 확대 방지

기존 `<style>` 블록에 추가:
```css
@media (max-width: 767px) {
  input, select, textarea { font-size: 16px !important; }
}
```
- 모바일(<md=768px)에서 모든 폼 컨트롤 글꼴을 16px로 → iOS Safari 포커스 자동 확대 차단. 검색창(`text-xs`)·태그 입력·URL·select 전부 적용.
- `!important`는 Tailwind 유틸(`text-xs`/`text-sm`, 클래스 우선순위)을 이겨야 해서 필요. iOS zoom의 표준 워크어라운드.
- 데스크톱 무영향(미디어쿼리 <768px 한정).

## 테스트 / 검증

### 자동 (기존 문자열 검사 패턴)
- `/partials/input/youtube` 응답에 `flex flex-col md:flex-row` 포함.
- `/` 응답(base.html)에 iOS 줌 규칙 마커 포함: `max-width: 767px` 와 `font-size: 16px`.
- 전체 스위트 유지(현재 264).

### 수동 (Playwright 모바일 390폭 + 실기기)
1. Playwright: 모바일 폭에서 `+ 분석` 펼친 뒤 `document.documentElement.scrollWidth <= clientWidth`(가로 오버플로 없음), 폼이 세로 스택.
2. 데스크톱 폭: 입력 폼 현행 한 줄 유지.
3. 실기기(iOS Safari): 검색창·URL 입력 포커스 시 화면이 확대되지 않음.

## 비목표 (YAGNI)
- pdf/code/text/markdown 입력 partial 레이아웃(모바일 비노출).
- safe-area-inset(노치/홈인디케이터), 하단 툴바, 스크롤 점프 등 — 관찰된 증상 없음. 필요 시 별도 spec.
- 데스크톱 레이아웃 변경.

## 분량 / 사이즈
- 수정 2개 파일: `input_youtube.html`(폼 클래스 2곳), `base.html`(`<style>` 미디어쿼리 1개).
- 테스트 신규 단언 2개.
- 단일 plan, 작은 규모.
