"""Shared Jinja2Templates instance with custom filters."""
import json
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
templates.env.filters["fromjson"] = json.loads
