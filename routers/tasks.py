from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from services.task_queue import get_task, queue_meta, cancel_task, dismiss_task
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
            f'<div id="task-{task.id}" class="note-card bg-red-50 border border-red-200 rounded-xl p-4 dark:bg-red-900/20 dark:border-red-800">'
            f'<div class="flex items-start gap-2">'
            f'<span class="flex-1 text-sm text-red-600 dark:text-red-400">분석 실패: {task.error}</span>'
            f'<button hx-post="/api/tasks/{task.id}/dismiss" hx-target="#task-{task.id}" hx-swap="outerHTML"'
            f' class="flex-shrink-0 text-[13px] text-red-400 hover:text-red-600 transition-colors px-1 leading-none"'
            f' title="닫기">✕</button>'
            f'</div></div>'
        )

    if task.status == "cancelled":
        # 카드 outerHTML 비워서 큐에서 제거
        return HTMLResponse("")

    return templates.TemplateResponse(request, "partials/task_card.html", {"task": task, **queue_meta(task)})


@router.post("/{task_id}/cancel")
async def cancel(task_id: str):
    """진행 중/대기 중 분석 취소. 다음 polling 때 카드가 사라진다(상태=cancelled→빈 응답)."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ok = await cancel_task(task_id)
    return HTMLResponse("", status_code=200 if ok else 409)


@router.post("/{task_id}/dismiss")
async def dismiss(task_id: str):
    """종결된 task(error/done/cancelled) 카드 닫기. 빈 응답으로 카드를 제거한다."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ok = await dismiss_task(task_id)
    return HTMLResponse("", status_code=200 if ok else 409)
