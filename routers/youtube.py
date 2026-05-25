from contextlib import asynccontextmanager
from fastapi import APIRouter, Form, Request
import aiosqlite
import config
from services.extractor import extract_youtube_full
from services.chapters import resolve_chapters
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

@asynccontextmanager
async def get_db_topics():
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            cursor = await db.execute("SELECT DISTINCT topic FROM items WHERE topic IS NOT NULL")
            rows = await cursor.fetchall()
        yield [r[0] for r in rows]
    except Exception:
        yield []

@router.post("")
async def analyze_youtube(
    request: Request,
    url: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    pid = parse_project_id(project_id)
    task = new_task("youtube", url)
    ai = get_provider(provider)

    async def do_work(t):
        t.progress = "YouTube 자막 추출 중..."
        data = await extract_youtube_full(url)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(data["text"], "youtube", mode, topics)
        t.title = result.title
        t.progress = "타임라인 생성 중..."
        chapters, ch_cost, ch_model = await resolve_chapters(
            data["native_chapters"], data["segments"], ai)
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid, timeline=chapters,
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        if ch_cost > 0:
            await record_api_cost(
                config.DB_PATH, ai.name(), model=ch_model,
                input_tokens=0, output_tokens=0, cost_usd=ch_cost, item_id=note_id,
            )
        t.note_id = note_id

    await enqueue(task, do_work)
    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
