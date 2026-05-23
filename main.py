from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from models import init_db
from templates_env import templates

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="liby", lifespan=lifespan)

from routers import youtube, pdf, items, settings
app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)

@app.get("/partials/input/{tab}")
async def get_input_partial(request: Request, tab: str) -> HTMLResponse:
    valid_tabs = {"youtube", "pdf", "markdown", "code"}
    if tab not in valid_tabs:
        tab = "youtube"
    return templates.TemplateResponse(request, f"partials/input_{tab}.html", {})

@app.get("/")
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})
