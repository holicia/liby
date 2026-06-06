"""Discord 봇. 메시지 디스패치(handle_message)는 discord 의존 없이 테스트 가능하게
분리하고, start_bot에서만 discord.Client를 배선한다."""
import asyncio
import logging

import config
from services.task_queue import get_task
from services import bot_core

log = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0
_POLL_MAX_TICKS = 300  # 약 10분 (2초 * 300)
_DETAIL_KEYWORDS = ("상세", "/detailed")


def _is_authorized(author_id) -> bool:
    allowed = config.DISCORD_ALLOWED_USER_ID
    return bool(allowed) and str(author_id) == str(allowed)


def _parse_mode(text: str) -> tuple[str, str]:
    """선두 키워드 뒤에 공백이 와야 detailed 명령으로 인정한다.
    'detailedfoo'·'상세분석' 같은 일반 단어를 오인하지 않도록 경계를 둔다.
    반환 (mode, 키워드 제거된 텍스트)."""
    lowered = text.lower()
    for kw in _DETAIL_KEYWORDS:
        if lowered.startswith(kw) and text[len(kw):][:1].isspace():
            stripped = text[len(kw):].strip()
            if stripped:
                return "detailed", stripped
    return "quick", text


async def _await_result(task_id: str, sleep=asyncio.sleep) -> dict:
    for _ in range(_POLL_MAX_TICKS):
        task = get_task(task_id)
        if task is None:
            return {"status": "error", "error": "task가 사라졌습니다"}
        if task.status in ("done", "error", "cancelled"):
            return {"status": task.status, "note_id": task.note_id, "error": task.error}
        await sleep(_POLL_INTERVAL)
    return {"status": "timeout", "error": "분석 시간 초과"}


async def handle_message(author_id, content: str, reply, is_bot: bool = False) -> None:
    """메시지 1건 처리. reply(text=None, embed=None)는 비동기 콜백."""
    if is_bot or not _is_authorized(author_id):
        return
    text = (content or "").strip()
    if not text:
        return
    mode, cleaned = _parse_mode(text)
    try:
        sub = await bot_core.submit_analysis(cleaned, mode=mode)
    except ValueError as e:
        await reply(text=f"⚠️ {e}")
        return
    await reply(text=f"⏳ 분석 시작… ({sub['kind']}, {mode})")
    res = await _await_result(sub["task_id"])
    if res["status"] == "done" and res.get("note_id"):
        payload = await bot_core.note_payload(res["note_id"])
        if payload:
            await reply(text="✅ 완료", embed=payload["embed"])
        else:
            await reply(text="완료했지만 노트를 찾지 못했습니다.")
    elif res["status"] == "timeout":
        await reply(text=f"⏱ {res['error']} (task {sub['task_id']})")
    else:
        await reply(text=f"❌ 분석 실패: {res.get('error') or res['status']}")


def _to_embed(embed_dict: dict):
    """포맷터의 dict → discord.Embed."""
    import discord
    e = discord.Embed(
        title=embed_dict.get("title"),
        description=embed_dict.get("description"),
        url=embed_dict.get("url"),
    )
    for f in embed_dict.get("fields", []):
        e.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
    return e


async def start_bot() -> None:
    """DISCORD_BOT_TOKEN이 있을 때만 기동. main.py lifespan에서 호출."""
    token = config.DISCORD_BOT_TOKEN
    if not token:
        log.info("DISCORD_BOT_TOKEN 미설정 — Discord 봇 비활성")
        return
    import discord
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Discord 봇 로그인: %s", client.user)

    @client.event
    async def on_message(message):
        async def reply(text=None, embed=None):
            await message.channel.send(
                content=text, embed=_to_embed(embed) if embed else None)
        await handle_message(message.author.id, message.content, reply,
                             is_bot=message.author.bot)

    try:
        await client.start(token)
    except Exception:
        log.exception("Discord 봇 비정상 종료")
