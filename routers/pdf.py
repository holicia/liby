import os
import tempfile
from fastapi import APIRouter, Form, Request, UploadFile, File
import config
from services.extractor import extract_pdf
from services.ai import get_provider
from services.storage import save_note, record_api_cost
from routers.youtube import get_db_topics, _result_to_dict
from templates_env import templates

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

@router.post("")
async def analyze_pdf(
    request: Request,
    file: UploadFile = File(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        text = await extract_pdf(tmp_path)
        ai = get_provider(provider)
        async with get_db_topics() as topics:
            result = await ai.summarize(text, "pdf", mode, topics)

        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="pdf", source_url=file.filename or "unknown.pdf",
            result=result, ai_provider=ai.name(),
        )
        await record_api_cost(
            config.DB_PATH, ai.name(),
            model=result.models_used[-1] if result.models_used else "",
            input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
            item_id=note_id,
        )
        return templates.TemplateResponse(
            request, "partials/note_card.html",
            {"note": _result_to_dict(note_id, result, "pdf", file.filename)},
        )
    finally:
        os.unlink(tmp_path)
