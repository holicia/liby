from fastapi import APIRouter, Query, Request
from typing import Optional
import config
from services.ai import get_provider
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes,
)
from templates_env import templates

router = APIRouter(prefix="/api/items", tags=["items"])

@router.get("")
async def get_items(
    request: Request,
    topic: Optional[str] = Query(None),
    tags: list[str] = Query([]),
    search: Optional[str] = Query(None),
):
    notes = await list_notes(config.DB_PATH, topic=topic, tags=tags, search=search)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes},
    )

@router.get("/topics")
async def get_topics_partial(request: Request):
    topics = await get_topics(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/sidebar_topics.html",
        {"topics": topics},
    )

@router.get("/random")
async def get_random_notes_partial(request: Request):
    notes = await get_random_notes(config.DB_PATH, n=4)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes},
    )

@router.get("/{note_id}")
async def get_item(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    return templates.TemplateResponse(
        request, "partials/note_card.html",
        {"note": note},
    )

@router.post("/{note_id}/upgrade")
async def upgrade_note(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note:
        return {"error": "노트를 찾을 수 없습니다."}

    provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))
    detailed = await provider.run_tier3(note["summary"])
    await upgrade_to_detailed(config.DB_PATH, note_id, detailed)
    await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, detailed.cost_usd, note_id)

    updated_note = await get_note(config.DB_PATH, note_id)
    return templates.TemplateResponse(
        request, "partials/note_card.html",
        {"note": updated_note},
    )
