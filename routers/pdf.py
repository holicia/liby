import os
import re
import tempfile
import uuid
from fastapi import APIRouter, Form, Request, UploadFile, File
import config
from services.extractor import extract_pdf
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from services import pdf_figures
from services.task_queue import new_task, enqueue, queue_meta
from routers.youtube import get_db_topics
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


def _figure_slug(filename: str) -> str:
    base = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    base = re.sub(r"[^A-Za-z0-9가-힣]+", "-", base).strip("-")[:40] or "paper"
    return f"{base}-{uuid.uuid4().hex[:6]}"


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
    pid = parse_project_id(project_id)
    task = new_task("pdf", filename)
    ai = get_provider(provider)

    async def do_work(t):
        t.progress = "PDF 텍스트·그림 추출 중..."
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            text = await extract_pdf(tmp_path)
            # 논문 그림 추출 — vault/pdf/<slug>/figN.<ext>에 저장
            fig_root = os.path.join(config.VAULT_PATH, "pdf")
            slug = _figure_slug(filename)
            try:
                figures = pdf_figures.extract_figures(tmp_path, fig_root, slug)
            except Exception:
                figures = []
        finally:
            os.unlink(tmp_path)
        t.progress = "AI 분석 중(논문 5개 항목)..."
        async with get_db_topics() as topics:
            result = await ai.summarize_paper(
                text, pdf_figures.figures_manifest(figures), topics)
        # LLM이 배치한 figure 번호를 실제 그림으로 치환, 남은 그림은 갤러리로 첨부
        if result.sections and figures:
            placed = pdf_figures.attach_figures_to_sections(result.sections, figures)
            gallery = pdf_figures.build_gallery_section(figures, placed)
            if gallery:
                result.sections.append(gallery)
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
