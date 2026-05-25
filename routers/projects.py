from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
import config
from services.storage import (
    list_projects, unassigned_count, create_project, rename_project, delete_project,
)
from templates_env import templates

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _render_list(request: Request) -> HTMLResponse:
    projects = await list_projects(config.DB_PATH)
    unassigned = await unassigned_count(config.DB_PATH)
    resp = templates.TemplateResponse(
        request, "partials/sidebar_projects.html",
        {"projects": projects, "unassigned": unassigned},
    )
    resp.headers["HX-Trigger"] = "projectsChanged"
    return resp


@router.get("")
async def get_projects(request: Request):
    return await _render_list(request)


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
        except Exception:
            pass  # 중복/빈값 등은 무시하고 목록 재렌더
    return await _render_list(request)


@router.patch("/{project_id}")
async def edit_project(request: Request, project_id: int, name: str = Form(...)):
    name = name.strip()
    if name:
        await rename_project(config.DB_PATH, project_id, name)
    return await _render_list(request)


@router.delete("/{project_id}")
async def remove_project(request: Request, project_id: int):
    await delete_project(config.DB_PATH, project_id)
    return await _render_list(request)
