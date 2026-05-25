from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from services.task_queue import get_task, queue_meta
from templates_env import templates

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("/{task_id}")
async def get_task_status(request: Request, task_id: str):
    task = get_task(task_id)
    if not task:
        return HTMLResponse('<p class="text-sm text-red-400 py-2">오류: 작업을 찾을 수 없습니다.</p>')

    if task.status == "done" and task.note_id:
        # 대기열 카드를 비우고(outerHTML), 메인 노트 목록 새로고침을 트리거
        resp = HTMLResponse("")
        resp.headers["HX-Trigger"] = "noteCompleted"
        return resp

    if task.status == "error":
        return HTMLResponse(
            f'<div class="note-card bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-600 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">'
            f'분석 실패: {task.error}</div>'
        )

    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})
