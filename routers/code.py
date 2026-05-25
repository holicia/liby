from fastapi import APIRouter, Form, Request
import config
from services.extractor import extract_github_repo
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta
from routers.youtube import get_db_topics
from templates_env import templates

router = APIRouter(prefix="/api/code", tags=["code"])

@router.post("")
async def analyze_code(
    request: Request,
    url: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    pid = int(project_id) if project_id.strip() else None
    task = new_task("code", url)
    ai = get_provider(provider)

    async def do_work(t):
        t.progress = "GitHub 정보 수집 중..."
        text, _repo_name = await extract_github_repo(url)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(text, "code", mode, topics)
        t.title = result.title
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="code", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid,
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        t.note_id = note_id

    await enqueue(task, do_work)
    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
