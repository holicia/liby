from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
import aiosqlite
import config
from services.storage import (
    list_projects, unassigned_count, create_project, rename_project, delete_project,
    list_notes_for_digest, save_project_digest, get_project_digest,
)
from templates_env import templates

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _render_sidebar(request: Request, *, notify: bool):
    projects = await list_projects(config.DB_PATH)
    unassigned = await unassigned_count(config.DB_PATH)
    resp = templates.TemplateResponse(
        request, "partials/sidebar_projects.html",
        {"projects": projects, "unassigned": unassigned},
    )
    if notify:
        # 프로젝트 목록이 바뀐 변경(POST/PATCH/DELETE)에서만 트리거.
        # GET에서 보내면 사이드바가 다시 GET을 호출해 무한 루프가 된다.
        resp.headers["HX-Trigger"] = "projectsChanged"
    return resp


@router.get("")
async def get_projects(request: Request):
    return await _render_sidebar(request, notify=False)


@router.get("/options")
async def get_project_options(request: Request):
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(request, "partials/project_options.html", {"projects": projects})


@router.post("")
async def add_project(request: Request, name: str = Form(...)):
    name = name.strip()
    if name:
        try:
            await create_project(config.DB_PATH, name)
        except aiosqlite.IntegrityError:
            pass  # 중복 이름은 무시하고 목록 재렌더
    return await _render_sidebar(request, notify=True)


@router.patch("/{project_id}")
async def edit_project(request: Request, project_id: int, name: str = Form(...)):
    name = name.strip()
    if name:
        try:
            await rename_project(config.DB_PATH, project_id, name)
        except aiosqlite.IntegrityError:
            pass  # 중복 이름은 무시하고 목록 재렌더
    return await _render_sidebar(request, notify=True)


@router.delete("/{project_id}")
async def remove_project(request: Request, project_id: int):
    await delete_project(config.DB_PATH, project_id)
    return await _render_sidebar(request, notify=True)


# --- 프로젝트 통합 정리(digest) ---

def _render_digest_panel(request: Request, project_id: int,
                        cached: dict | None) -> "HTMLResponse":
    """프로젝트 클릭 시 main 위에 들어가는 정리 패널.
    cached가 있으면 결과 표시, 없으면 '정리하기' 버튼만."""
    return templates.TemplateResponse(
        request, "partials/project_digest.html",
        {"project_id": project_id, "cached": cached},
    )


@router.get("/{project_id}/digest")
async def get_digest(request: Request, project_id: int):
    cached = await get_project_digest(config.DB_PATH, project_id)
    return _render_digest_panel(request, project_id, cached)


@router.post("/{project_id}/digest")
async def create_digest(
    request: Request, project_id: int,
    provider: str = Form("claude-cli"),
):
    """프로젝트 노트를 모아 LLM으로 통합 정리. 기존 캐시는 덮어씀."""
    notes = await list_notes_for_digest(config.DB_PATH, project_id)
    if not notes:
        raise HTTPException(status_code=400, detail="프로젝트에 노트가 없습니다")
    adapter_map = {"claude-cli": "claude", "codex-cli": "codex"}
    adapter = adapter_map.get(provider)
    if adapter is None:
        raise HTTPException(status_code=400,
                            detail=f"지원 안 하는 provider: {provider} (claude-cli/codex-cli만)")
    from services.digest import build_project_digest
    try:
        digest, model = await build_project_digest(notes, adapter=adapter)
    except Exception as e:
        # 에러는 진단 메시지 포함해 사용자에게 노출
        return HTMLResponse(
            f'<div class="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3">'
            f'정리 실패: {str(e)[:300]}</div>',
            status_code=200,
        )
    await save_project_digest(
        config.DB_PATH, project_id, digest,
        note_count=len(notes), provider=provider, model=model,
    )
    cached = await get_project_digest(config.DB_PATH, project_id)
    return _render_digest_panel(request, project_id, cached)
