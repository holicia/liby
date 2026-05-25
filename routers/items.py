from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional
import os
import config
from services.ai import get_provider
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes,
    list_projects, set_note_project, set_timeline,
)
from services.extractor import youtube_video_id, extract_youtube_full
from services.chapters import resolve_chapters
from routers._utils import parse_project_id
from templates_env import templates

router = APIRouter(prefix="/api/items", tags=["items"])

@router.get("")
async def get_items(
    request: Request,
    topic: Optional[str] = Query(None),
    tags: list[str] = Query([]),
    search: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
):
    notes = await list_notes(config.DB_PATH, topic=topic, tags=tags, search=search, project_id=project_id)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes, "projects": projects},
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
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes, "projects": projects},
    )

@router.get("/{note_id}/detail")
async def get_item_detail(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    video_id = None
    if note and note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": note, "video_id": video_id},
    )

@router.post("/{note_id}/timeline")
async def backfill_timeline(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note or not note.get("source_url"):
        return templates.TemplateResponse(
            request, "partials/note_detail_modal.html", {"note": note, "video_id": None})
    data = await extract_youtube_full(note["source_url"])
    provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))
    chapters, cost, model = await resolve_chapters(data["native_chapters"], data["segments"], provider)
    await set_timeline(config.DB_PATH, note_id, chapters)
    if cost > 0:
        await record_api_cost(config.DB_PATH, provider.name(), model, 0, 0, cost, note_id)
    updated = await get_note(config.DB_PATH, note_id)
    video_id = youtube_video_id(updated["source_url"]) if updated.get("source_url") else None
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": updated, "video_id": video_id},
    )

@router.post("/{note_id}/project")
async def set_item_project(request: Request, note_id: int, project_id: str = Form("")):
    pid = parse_project_id(project_id)
    await set_note_project(config.DB_PATH, note_id, pid)
    note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    resp = templates.TemplateResponse(
        request, "partials/note_card.html", {"note": note, "projects": projects},
    )
    resp.headers["HX-Trigger"] = "projectsChanged"  # 사이드바/드롭다운 카운트 갱신
    return resp

@router.get("/{note_id}")
async def get_item(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_card.html",
        {"note": note, "projects": projects},
    )

@router.post("/{note_id}/open-md")
async def open_md_file(note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note or not note.get("md_file_path"):
        return JSONResponse({"error": "파일을 찾을 수 없습니다."}, status_code=404)
    path = note["md_file_path"]
    if not os.path.exists(path):
        return JSONResponse({"error": f"파일이 존재하지 않습니다: {path}"}, status_code=404)
    os.startfile(path)
    return JSONResponse({"ok": True})

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
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_card.html",
        {"note": updated_note, "projects": projects},
    )
