from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from typing import Optional
import os
from pathlib import Path
import config
from services.ai import get_provider
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes,
    list_projects, set_note_project, set_timeline,
    delete_note,
)
from services.extractor import youtube_video_id, extract_youtube_full, segments_to_transcript
from services.chapters import resolve_chapters
from services.task_queue import new_task, enqueue, queue_meta
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

@router.get("/count")
async def get_total_count():
    from fastapi.responses import PlainTextResponse
    from services.storage import count_notes
    n = await count_notes(config.DB_PATH)
    return PlainTextResponse(str(n))

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
    projects = await list_projects(config.DB_PATH)
    video_id = None
    if note and note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": note, "video_id": video_id, "projects": projects},
    )

@router.get("/{note_id}/read")
async def read_view(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    if not note:
        return RedirectResponse("/", status_code=302)
    video_id = (
        youtube_video_id(note.get("source_url"))
        if note.get("type") == "youtube" and note.get("source_url")
        else None
    )
    return templates.TemplateResponse(
        request, "read.html", {"note": note, "video_id": video_id},
    )


@router.delete("/{note_id}")
async def delete_item(note_id: int):
    md_path = await delete_note(config.DB_PATH, note_id)
    if md_path:
        try:
            Path(md_path).unlink()
        except FileNotFoundError:
            pass
    resp = HTMLResponse(content="", status_code=200)
    # 사이드바 #total-count + 미분류·프로젝트 카운트도 같이 갱신
    resp.headers["HX-Trigger"] = "noteDeleted, projectsChanged"
    return resp

@router.post("/{note_id}/timeline")
async def backfill_timeline(request: Request, note_id: int):
    note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    if not note or note.get("type") != "youtube" or not note.get("source_url"):
        return templates.TemplateResponse(
            request, "partials/note_detail_modal.html",
            {"note": note, "video_id": None, "projects": projects})
    try:
        data = await extract_youtube_full(note["source_url"])
        provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))
        chapters, cost, model = await resolve_chapters(data["native_chapters"], data["segments"], provider)
        await set_timeline(config.DB_PATH, note_id, chapters)
        if model:  # AI 호출 발생 시 기록(native chapters는 model=""). CLI는 cost=0이라도 카운트.
            await record_api_cost(config.DB_PATH, provider.name(), model, 0, 0, cost, note_id)
    except Exception:
        # 자막 없음/네트워크 오류 등은 500 대신 모달을 그대로 재렌더(타임라인 없이)
        pass
    updated = await get_note(config.DB_PATH, note_id)
    video_id = youtube_video_id(updated["source_url"]) if updated.get("source_url") else None
    return templates.TemplateResponse(
        request, "partials/note_detail_modal.html",
        {"note": updated, "video_id": video_id, "projects": projects},
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

    task = new_task(note["type"], note["title"])
    provider = get_provider(note.get("ai_provider", config.DEFAULT_AI_PROVIDER))

    async def do_work(t):
        is_yt = note.get("type") == "youtube" and note.get("source_url")
        if is_yt:
            # 핵심 상세 정리(추출→요약→저장)는 실패 시 예외를 전파해 큐가 오류로 표시한다.
            t.progress = "상세 분석 중..."
            data = await extract_youtube_full(note["source_url"])
            src = segments_to_transcript(data["segments"]) if data["segments"] else data["text"]
            full = await provider.summarize(src, "youtube", "detailed", [])
            await upgrade_to_detailed(config.DB_PATH, note_id, full)
            await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, full.cost_usd, note_id)
            try:  # 타임라인은 부가 기능 → 실패해도 상세 정리는 유지
                t.progress = "타임라인 생성 중..."
                chapters, cost, model = await resolve_chapters(
                    data["native_chapters"], data["segments"], provider)
                await set_timeline(config.DB_PATH, note_id, chapters)
                if model:  # AI 호출 발생 시 기록. CLI는 cost=0이라도 카운트.
                    await record_api_cost(config.DB_PATH, provider.name(), model, 0, 0, cost, note_id)
            except Exception:
                pass
        else:
            t.progress = "상세 분석 중..."
            detailed = await provider.run_tier3(note["summary"])
            await upgrade_to_detailed(config.DB_PATH, note_id, detailed)
            await record_api_cost(config.DB_PATH, provider.name(), "", 0, 0, detailed.cost_usd, note_id)
        t.note_id = note_id

    await enqueue(task, do_work)
    return templates.TemplateResponse(
        request, "partials/task_card.html", {"task": task, **queue_meta(task)},
    )
