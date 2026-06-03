from contextlib import asynccontextmanager
from fastapi import APIRouter, Form, Request
import aiosqlite
import config
from services.extractor import extract_youtube_full, segments_to_transcript, youtube_title
from services.chapters import resolve_chapters
from services.ai import get_provider
from services.storage import save_note, record_api_cost, safe_filename
from services.task_queue import new_task, enqueue, queue_meta, register_builder
from services.capture import capture_chapter_screenshots
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

@asynccontextmanager
async def get_db_topics():
    # try는 DB 조회만 감싸고, yield는 정확히 한 번만(본문 예외가 athrow로 던져져도
    # except가 다시 yield하지 않도록) — 그래야 본문의 진짜 예외가 그대로 전파됨.
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            cursor = await db.execute("SELECT DISTINCT topic FROM items WHERE topic IS NOT NULL")
            rows = await cursor.fetchall()
        topics = [r[0] for r in rows]
    except Exception:
        topics = []
    yield topics

def _build_youtube_do_work(spec: dict):
    """spec → 분석 코루틴 생성. task_queue가 영구화·재시도 시 이 builder로 재구성한다."""
    url = spec["url"]
    provider = spec["provider"]
    mode = spec.get("mode", "quick")
    pid = spec.get("project_id")

    async def do_work(t):
        ai = get_provider(provider)
        t.progress = "YouTube 자막 추출 중..."
        data = await extract_youtube_full(url)
        t.progress = "AI 분석 중..."
        if data["segments"]:
            summarize_input = segments_to_transcript(data["segments"])
        else:
            summarize_input = data["text"]
        async with get_db_topics() as topics:
            result = await ai.summarize(summarize_input, "youtube", mode, topics)
        t.title = result.title
        t.progress = "타임라인 생성 중..."
        chapters, ch_cost, ch_model = await resolve_chapters(
            data["native_chapters"], data["segments"], ai)
        # detailed mode: sections heading+t를 타임라인으로 채택해 본문 섹션과 일치시킴.
        # t가 누락된 section(LLM이 부여 못함)은 직전 t + 30초로 fallback해 timeline에서 빠지지 않도록.
        # quick은 그대로 native/AI chapters 사용.
        if mode == "detailed" and result.sections:
            chapters = []
            last_t = 0
            for sec in result.sections:
                if not sec.get("heading"):
                    continue
                sec_t = sec.get("t")
                sec_t = int(sec_t) if sec_t is not None else last_t + 30
                chapters.append({"t": sec_t, "label": sec["heading"]})
                last_t = sec_t
        if chapters:
            t.progress = "스크린샷 캡처 중..."
            chapters = await capture_chapter_screenshots(
                url, chapters, config.VAULT_PATH, safe_filename(result.title))
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
            segments=data["segments"],
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        # AI 호출이 실제로 발생한 경우 record (model이 채워짐). native chapters 그대로
        # 쓴 경우엔 model=""이라 skip. cost>0 가드는 CLI(cost=0)를 누락시키므로 사용 안 함.
        if ch_model:
            await record_api_cost(
                config.DB_PATH, ai.name(), model=ch_model,
                input_tokens=0, output_tokens=0, cost_usd=ch_cost, item_id=note_id,
            )
        t.note_id = note_id

    return do_work


# 모듈 import 시점에 builder 등록(main.py가 라우터를 import할 때 자동 실행).
register_builder("youtube", _build_youtube_do_work)


@router.post("")
async def analyze_youtube(
    request: Request,
    url: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    pid = parse_project_id(project_id)
    # oEmbed로 영상 제목을 미리 가져와 큐 카드에 표시(실패 시 URL 폴백)
    title = await youtube_title(url) or url
    spec = {"source_type": "youtube", "url": url, "provider": provider,
            "mode": mode, "project_id": pid}
    task = new_task("youtube", title, spec=spec)
    await enqueue(task)  # coro_fn 생략 → worker가 builder로 재구성, 영구화·재시도 가능
    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
