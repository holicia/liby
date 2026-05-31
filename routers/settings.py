from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
import config
from templates_env import templates

router = APIRouter(prefix="/api/settings", tags=["settings"])

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


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


@router.get("/usage")
async def usage_report(request: Request):
    from services.storage import get_monthly_cost, list_recent_api_costs
    claude_cost = await get_monthly_cost(config.DB_PATH, "claude")
    gpt_cost = await get_monthly_cost(config.DB_PATH, "gpt")
    rows = await list_recent_api_costs(config.DB_PATH, limit=100)
    for r in rows:
        raw = r.get("recorded_at")
        if raw:
            try:
                dt = datetime.fromisoformat(raw).replace(tzinfo=UTC)
                r["recorded_at_kst"] = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                r["recorded_at_kst"] = raw
        else:
            r["recorded_at_kst"] = ""
    return templates.TemplateResponse(
        request, "usage.html",
        {
            "claude_cost": claude_cost,
            "claude_limit": config.CLAUDE_MONTHLY_LIMIT_USD,
            "gpt_cost": gpt_cost,
            "gpt_limit": config.GPT_MONTHLY_LIMIT_USD,
            "rows": rows,
        },
    )
