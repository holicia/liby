from contextlib import asynccontextmanager
from fastapi import APIRouter, Form, Request
import aiosqlite
import config
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta, register_builder
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/text", tags=["text"])


@asynccontextmanager
async def get_db_topics():
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            cursor = await db.execute("SELECT DISTINCT topic FROM items WHERE topic IS NOT NULL")
            rows = await cursor.fetchall()
        topics = [r[0] for r in rows]
    except Exception:
        topics = []
    yield topics


def _build_text_do_work(spec: dict):
    """spec → 분석 코루틴. task_queue가 영구화·재시도 시 이 builder로 재구성한다."""
    content = spec["content"]
    provider = spec["provider"]
    mode = spec.get("mode", "quick")
    pid = spec.get("project_id")

    async def do_work(t):
        ai = get_provider(provider)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(content, "text", mode, topics)
        t.title = result.title
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="text", source_url=content[:100],
            result=result, ai_provider=ai.name(), project_id=pid,
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        t.note_id = note_id

    return do_work


register_builder("text", _build_text_do_work)


@router.post("")
async def analyze_text(
    request: Request,
    content: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    content = content.strip()
    pid = parse_project_id(project_id)
    spec = {"source_type": "text", "content": content, "provider": provider,
            "mode": mode, "project_id": pid}
    task = new_task("text", content[:40], spec=spec)
    await enqueue(task)  # coro_fn 생략 → builder 재구성, 영구화·재시도
    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
