import os
import tempfile
from fastapi import APIRouter, Form, Request, UploadFile, File
import config
from services.extractor import extract_pdf
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services.task_queue import new_task, enqueue, queue_meta
from routers.youtube import get_db_topics
from templates_env import templates

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

@router.post("")
async def analyze_pdf(
    request: Request,
    file: UploadFile = File(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    file_bytes = await file.read()
    filename = file.filename or "unknown.pdf"
    pid = int(project_id) if project_id.strip() else None
    task = new_task("pdf", filename)
    ai = get_provider(provider)

    async def do_work(t):
        t.progress = "PDF 텍스트 추출 중..."
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            text = await extract_pdf(tmp_path)
        finally:
            os.unlink(tmp_path)
        t.progress = "AI 분석 중..."
        async with get_db_topics() as topics:
            result = await ai.summarize(text, "pdf", mode, topics)
        t.title = result.title
        t.progress = "저장 중..."
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="pdf", source_url=filename,
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
