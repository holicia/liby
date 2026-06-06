"""Discord 봇과 /api/bot 라우터가 공유하는 분석 트리거·결과 조립 로직.
in-process 호출(봇)과 HTTP(라우터)가 같은 코드를 쓰도록 한 곳에 둔다."""
import config
from services.extractor import youtube_video_id
from services.task_queue import new_task, enqueue
from services.storage import get_note
from services.discord_format import build_embed


async def submit_analysis(input_text: str, mode: str = "quick",
                          project_id: int | None = None) -> dict:
    """입력을 유튜브/텍스트로 판별해 task를 큐에 넣는다.
    반환 {task_id, title, kind}. 빈 입력이면 ValueError."""
    text = (input_text or "").strip()
    if not text:
        raise ValueError("빈 입력입니다")
    video_id = youtube_video_id(text)
    if video_id:
        spec = {"source_type": "youtube", "url": text,
                "provider": config.DEFAULT_AI_PROVIDER, "mode": mode,
                "project_id": project_id}
        task = new_task("youtube", text, spec=spec)
        kind = "youtube"
    else:
        spec = {"source_type": "text", "content": text,
                "provider": config.DEFAULT_AI_PROVIDER, "mode": mode,
                "project_id": project_id}
        task = new_task("text", text[:40], spec=spec)
        kind = "text"
    await enqueue(task)  # coro_fn 생략 → builder 재구성, 영구화·재시도
    return {"task_id": task.id, "title": task.title, "kind": kind}


async def note_payload(note_id: int) -> dict | None:
    """노트 → 봇 임베드용 payload. 없으면 None."""
    note = await get_note(config.DB_PATH, note_id)
    if note is None:
        return None
    video_id = None
    if note.get("type") == "youtube" and note.get("source_url"):
        video_id = youtube_video_id(note["source_url"])
    note["video_id"] = video_id
    note["read_url"] = f"{config.PUBLIC_BASE_URL}/api/items/{note_id}/read"
    return {
        "id": note_id,
        "title": note.get("title"),
        "read_url": note["read_url"],
        "embed": build_embed(note),
    }
