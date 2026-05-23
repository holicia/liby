from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from models import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="liby", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

from routers import youtube, pdf
app.include_router(youtube.router)
app.include_router(pdf.router)

@app.get("/")
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})
