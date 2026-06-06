from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import config
from services.task_queue import get_task
from services import bot_core

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _check_token(x_bot_token: str | None) -> None:
    if config.BOT_API_TOKEN and x_bot_token != config.BOT_API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid bot token")


class AnalyzeIn(BaseModel):
    input: str
    mode: str = "quick"
    project_id: int | None = None


@router.post("/analyze")
async def bot_analyze(body: AnalyzeIn, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    try:
        return await bot_core.submit_analysis(body.input, mode=body.mode, project_id=body.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks/{task_id}")
async def bot_task(task_id: str, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"status": task.status, "note_id": task.note_id,
            "error": task.error, "title": task.title}


@router.get("/notes/{note_id}")
async def bot_note(note_id: int, x_bot_token: str | None = Header(default=None)):
    _check_token(x_bot_token)
    payload = await bot_core.note_payload(note_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="note not found")
    return payload
