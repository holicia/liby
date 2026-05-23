from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

app = FastAPI(title="liby")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
