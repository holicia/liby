# YouTube 챕터별 영상 스크린샷 캡처 (2026-05-31)

YouTube 노트의 각 챕터 시작 시각에서 영상 프레임을 1장씩 추출해 vault에 저장하고, 모달에서 "📷 스크린샷 보기" 토글로 그리드 펼침 노출. Lilys AI의 챕터 캡처 패턴을 모방.

**대상 분량:** M (구현 사이클 1회, 단일 plan)
**테스트 카운트 변동 예상:** +7 (capture 4 / route 1 / modal 2)

---

## 동기
- 영상 노트의 챕터 라벨만으로는 시각적 단서가 부족. 캡처 1장이면 챕터의 슬라이드/장면을 즉시 식별 가능.
- 사용자가 동시에 검토를 시도한 Lilys AI 노트의 챕터 옆 캡처 패턴(2열 그리드)을 참고로 함.
- vault에 jpg로 저장되므로 Obsidian에서도 동일하게 보임(상대 경로 이미지 링크).

---

## 핵심 결정 사항 (브레인스토밍 합의)

| 항목 | 결정 |
|---|---|
| 트리거 | YouTube 분석 시 항상 자동 (고정 On) |
| 캡처 소스 | `yt-dlp --download-sections "*t-t+2"` 슬라이스 다운 + `ffmpeg`로 첫 프레임 jpg 추출 |
| 저장 위치 | `vault/youtube/<note-slug>/ch-N.jpg` (md 파일 옆 폴더) |
| 모달 UI | "📷 스크린샷 보기" 전체 토글 1개 → 펼치면 2열 그리드 |

---

## 아키텍처 / 데이터 흐름

```
analyze_youtube(do_work):
  ...
  chapters, ch_cost, ch_model = resolve_chapters(...)
  ── NEW ────────────────────────────────────────────────────
  t.progress = "스크린샷 캡처 중..."
  chapters = await capture_chapter_screenshots(url, chapters, vault_path, note_slug)
  ── /NEW ───────────────────────────────────────────────────
  save_note(..., timeline=chapters)
```

`capture_chapter_screenshots`가 chapters에 `image` 키를 추가해 반환. 실패한 챕터는 키 생략(부분 성공 허용).

**chapter dict 확장:**
```jsonc
{
  "t": 90,
  "label": "도입부 설명",
  "image": "코끼리관찰현장메모/ch-2.jpg"  // vault/youtube/ 기준 상대 경로
}
```

---

## 컴포넌트

### 신규: `services/capture.py`
**책임:** YouTube URL + chapters → 챕터별 jpg 캡처 후 chapters에 `image` 키 추가.

```python
async def capture_chapter_screenshots(
    url: str,
    chapters: list[dict],
    vault_path: str,
    note_slug: str,   # save_note의 _safe_filename(result.title) 와 동일
) -> list[dict]:
    """각 챕터 시작 시각의 영상 프레임을 vault/youtube/<note_slug>/ch-N.jpg로 저장.
    실패한 챕터는 image 키 없이 반환(부분 성공)."""
```

**내부 구현 요지:**
- 빈 chapters → 빈 리스트 반환.
- 출력 디렉토리: `os.path.join(vault_path, "youtube", note_slug)` 생성(`exist_ok=True`).
- 각 챕터 i, t에 대해:
  1. 임시 mp4 경로 `tempfile.mkstemp(suffix=".mp4")`.
  2. `yt_dlp.YoutubeDL({"format": "best[height<=720]", "download_sections": [f"*{t}-{t+2}"], "outtmpl": tmp_mp4, "quiet": True})`로 슬라이스 다운.
  3. `subprocess.run(["ffmpeg", "-y", "-ss", "0", "-i", tmp_mp4, "-frames:v", "1", "-q:v", "5", out_jpg], timeout=30, capture_output=True)`.
  4. 성공 시 chapter dict에 `"image": f"{note_slug}/ch-{i+1}.jpg"` 추가.
  5. 임시 mp4 unlink (finally).
- subprocess.run은 동기 → 전체 함수를 `asyncio.run_in_executor`로 감쌈(yt-dlp도 동기 라이브러리).
- 예외 처리:
  - `FileNotFoundError` (ffmpeg 미설치): 첫 호출 시 logger.warning 1회, 모든 챕터 skip(원본 chapters 반환).
  - `subprocess.TimeoutExpired`, `yt_dlp.utils.DownloadError`, `subprocess.CalledProcessError`: 해당 챕터만 skip, 다음 챕터로 계속.
  - `OSError`(디스크 풀, 권한): 해당 챕터만 skip, 로그.

### 수정: `routers/youtube.py`
`analyze_youtube` do_work에서 `resolve_chapters` 직후, `save_note` 직전에 캡처 단계 삽입. `note_slug`는 `services.storage._safe_filename(result.title)`을 호출해 동일하게 얻음(또는 `_safe_filename`을 storage에서 import).

```python
t.progress = "타임라인 생성 중..."
chapters, ch_cost, ch_model = await resolve_chapters(...)
if chapters:
    t.progress = "스크린샷 캡처 중..."
    from services.storage import _safe_filename
    chapters = await capture_chapter_screenshots(
        url, chapters, config.VAULT_PATH, _safe_filename(result.title)
    )
t.progress = "저장 중..."
note_id = await save_note(..., timeline=chapters)
```

### 수정: `templates/partials/note_detail_modal.html`
현재 `## 챕터` 섹션(timeline list 렌더)이 있음. 그 끝에 단일 토글 + 그리드 추가:

```html
{% if note.timeline %}
{% set timeline_list = note.timeline if note.timeline is not string else (note.timeline | fromjson) %}
{% set has_images = timeline_list | selectattr('image', 'defined') | list | length > 0 %}
{% if has_images %}
<details class="mt-3">
  <summary class="cursor-pointer text-[11px] font-bold text-[#1F6F4A] dark:text-[#34A66A] hover:underline select-none">
    📷 스크린샷 보기
  </summary>
  <div class="grid grid-cols-2 gap-3 mt-3">
    {% for ch in timeline_list %}
      {% if ch.image is defined %}
      <div class="text-[11px]">
        <button type="button"
                onclick="event.preventDefault(); event.stopPropagation(); ytSeek({{ ch.t }})"
                class="block w-full">
          <img src="/vault/youtube/{{ ch.image }}"
               alt="{{ ch.label }}"
               class="w-full rounded-lg border border-[#E2E8E4] dark:border-gray-700 hover:opacity-90 transition-opacity">
        </button>
        <div class="mt-1 text-gray-600 dark:text-gray-400 flex items-center gap-1">
          <span class="font-mono text-[#1F6F4A] dark:text-[#34A66A]">⏱{{ fmt_ts(ch.t) }}</span>
          <span class="truncate">{{ ch.label }}</span>
        </div>
      </div>
      {% endif %}
    {% endfor %}
  </div>
</details>
{% endif %}
{% endif %}
```

이미지 클릭 시 `ytSeek(ch.t)`로 영상 이동. 토글 닫혀 있는 게 기본(`open` 속성 없음).

### 신규: 정적 파일 마운트
`main.py`에 vault 디렉토리를 정적으로 서빙해야 `<img src="/vault/...">`가 동작. `app.mount("/vault", StaticFiles(directory=config.VAULT_PATH), name="vault")` 1줄 추가(FastAPI에 이미 StaticFiles 사용 X — 신규 의존 검토). 또는 별도 라우트로 `GET /vault/{path:path}` 핸들러.

→ **결정:** `app.mount("/vault", StaticFiles(...))`가 가장 단순. FastAPI에 내장된 starlette StaticFiles 사용, 추가 의존 없음.

---

## 데이터 모델
DB 컬럼 `items.timeline`(JSON TEXT)은 그대로. 챕터 dict 형태만 `{t, label}` → `{t, label, image?}` 확장. 백워드 호환: 기존 노트의 timeline은 image 키 없음 → 모달의 `has_images` 가드로 토글 숨김.

---

## 에러 처리
- **ffmpeg/yt-dlp 미설치**: 캡처 단계 전체 silently skip. 분석은 정상 종료. 로그 1회. timeline에 image 키 없음 → 모달 토글 숨김.
- **챕터 1개 실패** (subprocess timeout / yt-dlp download error): 해당 챕터만 image 없이, 나머지 진행.
- **vault 디스크 오류**: 해당 챕터 skip, 로그. 분석 본체 정상.
- **사용자 친화 메시지 노출 X**: 캡처는 부가 기능이라 silently degrade. 진행 메시지 "스크린샷 캡처 중..."만 표시.

---

## 테스트

### `tests/test_capture.py` (신규)
- `test_capture_skips_when_chapters_empty`: 빈 chapters 입력 → 빈 리스트, subprocess 호출 0.
- `test_capture_adds_image_path_on_success`: mock yt-dlp + mock subprocess(ffmpeg) → 2 챕터 둘 다 image 키 존재.
- `test_capture_skips_failed_chapter_continues_others`: 2 챕터 중 1개 ffmpeg 실패(non-zero exit) → 실패한 챕터는 image 없음, 나머지 정상.
- `test_capture_no_ffmpeg_returns_original_chapters`: subprocess `FileNotFoundError` → 모든 챕터 image 없이 원본 그대로 반환.

### `tests/test_routes_youtube.py` (추가)
- `test_youtube_pipes_chapters_with_images_to_save_note`: mock `capture_chapter_screenshots`가 image 추가된 chapters 반환 → save_note의 timeline kwarg에 image 키 포함된 chapters 전달.

### `tests/test_routes_items.py` (추가)
- `test_modal_renders_screenshot_toggle_when_timeline_has_images`: timeline에 image 키 있는 mock 노트 → `/api/items/{id}/detail` 응답에 `📷 스크린샷 보기`와 `<img src="/vault/youtube/.../ch-1.jpg"` 포함.
- `test_modal_hides_screenshot_toggle_when_no_images`: image 키 없는 timeline → 토글 마크업 없음.

### main.py (변경 시)
- 기존 `tests/test_routes_partials.py`나 새 케이스에서 `GET /vault/youtube/test/ch-1.jpg` 같은 정적 파일 라우트가 마운트됐는지(404가 아니라 적절히 처리되는지) 가벼운 검증.

---

## Non-goals
- 챕터당 다중 이미지(Lilys는 2장씩 — 우리는 1장으로 시작, YAGNI).
- 이미지 후처리(크롭/리사이즈/워터마크).
- video_id 기반 캐싱(동일 영상 재분석 시 재캡처 OK — 디스크 부담 작음).
- vault .md 본문에 챕터+이미지 섹션 임베드(별도 follow-up — 모달만 우선).
- 백필 UI("기존 노트에 스크린샷 추가" 버튼). 필요해지면 별도 plan.
- 각주 ↔ 트랜스크립트 점프 기능(완전히 다른 데이터/프롬프트 변경 — 별도 brainstorm).

---

## 외부 의존성
- **ffmpeg**: 시스템 PATH에 있어야 함. 미설치 시 silently skip + README 명시 필요.
- **yt-dlp**: 이미 의존성에 있음(`services/extractor.py`).
- **starlette StaticFiles**: FastAPI 내장, 추가 의존 없음.

---

## 검증 (E2E)
1. `python -m pytest -q` — 모든 새 테스트 통과.
2. 서버 재시작 후 YouTube 영상(챕터 3~5개 있는 것) 분석.
3. 모달 열기 → `## 챕터` 섹션 아래 "📷 스크린샷 보기" 토글 보임.
4. 토글 펼치면 2열 그리드 + 각 이미지 클릭 시 영상 해당 시각으로 점프.
5. vault에 `vault/youtube/<note-slug>/ch-1.jpg, ch-2.jpg ...` 파일 존재 확인.
6. 옛 YouTube 노트(image 키 없는 timeline) 모달은 토글 자체가 안 보임.
7. ffmpeg 시스템에서 제거 후 새 분석 → 분석 완료되고 모달에 토글만 안 보임(에러 페이지 X).
