from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
import config

router = APIRouter(prefix="/api/settings", tags=["settings"])
templates = Jinja2Templates(directory="templates")

@router.get("/cost")
async def get_cost_widget(request: Request):
    from services.storage import get_monthly_cost
    claude_cost = await get_monthly_cost(config.DB_PATH, "claude")
    gpt_cost = await get_monthly_cost(config.DB_PATH, "gpt")
    return templates.TemplateResponse(
        request, "partials/api_cost.html",
        {
            "claude_cost": claude_cost,
            "claude_limit": config.CLAUDE_MONTHLY_LIMIT_USD,
            "gpt_cost": gpt_cost,
            "gpt_limit": config.GPT_MONTHLY_LIMIT_USD,
        },
    )
