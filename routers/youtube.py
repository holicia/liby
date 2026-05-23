from contextlib import asynccontextmanager
from fastapi import APIRouter, Form, Request
import aiosqlite
import config
from services.extractor import extract_youtube
from services.ai import get_provider
from services.storage import save_note, record_api_cost
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
):
    text, video_id = await extract_youtube(url)
    ai = get_provider(provider)

    async with get_db_topics() as topics:
        result = await ai.summarize(text, "youtube", mode, topics)

    note_id = await save_note(
        db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
        source_type="youtube", source_url=url,
        result=result, ai_provider=ai.name(),
    )
    await record_api_cost(
        config.DB_PATH, ai.name(),
        model=result.models_used[-1] if result.models_used else "",
        input_tokens=0, output_tokens=0, cost_usd=result.cost_usd,
        item_id=note_id,
    )
    return templates.TemplateResponse(
        request,
        "partials/note_card.html",
        {"note": _result_to_dict(note_id, result, "youtube", url, ai.name())},
    )

def _result_to_dict(note_id: int, result, source_type: str, source_url: str, ai_provider: str = "claude") -> dict:
    return {
        "id": note_id, "type": source_type, "source_url": source_url,
        "title": result.title, "summary": result.summary,
        "key_points": result.key_points, "tags": result.tags,
        "topic": result.suggested_topic, "summary_mode": result.summary_mode,
        "ai_provider": ai_provider, "cost_usd": result.cost_usd,
        "created_at": "방금 전",
    }
