import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from models import init_db
from templates_env import templates
from services.task_queue import run_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(run_worker())
    yield

app = FastAPI(title="liby", lifespan=lifespan)

from routers import youtube, pdf, items, settings, code, tasks, text
app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)
app.include_router(code.router)
app.include_router(tasks.router)
app.include_router(text.router)

@app.get("/partials/input/{tab}")
async def get_input_partial(request: Request, tab: str) -> HTMLResponse:
    valid_tabs = {"youtube", "pdf", "code", "text", "markdown"}
    if tab not in valid_tabs:
        tab = "youtube"
    return templates.TemplateResponse(request, f"partials/input_{tab}.html", {})

@app.get("/")
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})
