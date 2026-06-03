import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from models import init_db
from templates_env import templates
from services.task_queue import run_worker, restore_pending_tasks
import config

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(run_worker())
    # 라우터들이 이미 import되어 builder가 등록된 상태. orphan task를 큐에 다시 넣음.
    restored = await restore_pending_tasks()
    if restored:
        logging.getLogger(__name__).info(
            "restored %d pending task(s) from previous run", restored
        )
    yield

app = FastAPI(title="liby", lifespan=lifespan)

from routers import youtube, pdf, items, settings, code, tasks, text, projects, markdown
app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)
app.include_router(code.router)
app.include_router(tasks.router)
app.include_router(text.router)
app.include_router(projects.router)
app.include_router(markdown.router)

os.makedirs(config.VAULT_PATH, exist_ok=True)
app.mount("/vault", StaticFiles(directory=config.VAULT_PATH), name="vault")

@app.get("/partials/input/{tab}")
async def get_input_partial(request: Request, tab: str) -> HTMLResponse:
    valid_tabs = {"youtube", "pdf", "code", "text", "markdown"}
    if tab not in valid_tabs:
        tab = "youtube"
    return templates.TemplateResponse(request, f"partials/input_{tab}.html", {})

@app.get("/")
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})
