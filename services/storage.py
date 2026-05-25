import json
import os
import re
from datetime import datetime
import aiosqlite
from services.ai.base import SummaryResult

def _safe_filename(title: str) -> str:
    """제목을 파일명으로 안전하게 변환 (Windows 금지 문자 < > : " / \\ | ? * 및 공백 제거)."""
    safe = re.sub(r'[<>:"/\\|?*\s]+', "-", title[:40]).strip("-. ")
    return safe or "untitled"

def _make_md_content(
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "{result.title}"',
        f"type: {source_type}",
        f"source: {source_url}",
        f"tags: {json.dumps(result.tags, ensure_ascii=False)}",
        f"topic: {result.suggested_topic}",
        f"ai_provider: {ai_provider}",
        f"summary_mode: {result.summary_mode}",
        f"created: {today}",
        "---",
        "",
        "## 요약",
        result.summary,
        "",
        "## 핵심 포인트",
    ]
    for p in result.key_points:
        lines.append(f"- {p}")
    if result.main_arguments:
        lines += ["", "## 핵심 논거"]
        for a in result.main_arguments:
            lines.append(f"- {a}")
    if result.insights:
        lines += ["", "## 인사이트"]
        for i in result.insights:
            lines.append(f"- {i}")
    if result.questions_raised:
        lines += ["", "## 탐구할 질문"]
        for q in result.questions_raised:
            lines.append(f"- {q}")
    return "\n".join(lines)

async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-{_safe_filename(result.title)}.md"
    subdir = os.path.join(vault_path, source_type)
    os.makedirs(subdir, exist_ok=True)
    md_path = os.path.join(subdir, filename)

    md_content = _make_md_content(source_type, source_url, result, ai_provider)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, main_arguments, insights, questions_raised,
                related_concepts, ai_provider, ai_models, api_cost_usd, md_file_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, result.title, source_url, result.summary,
                json.dumps(result.key_points, ensure_ascii=False),
                json.dumps(result.sections, ensure_ascii=False),
                json.dumps(result.tags, ensure_ascii=False),
                result.suggested_topic, result.summary_mode,
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                ai_provider,
                json.dumps(result.models_used, ensure_ascii=False),
                result.cost_usd, md_path,
            )
        )
        await db.commit()
        return cursor.lastrowid

async def get_note(db_path: str, note_id: int) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM items WHERE id = ?", (note_id,))
        row = await cursor.fetchone()
        return _parse_row(dict(row)) if row else None

async def record_api_cost(
    db_path: str, provider: str, model: str,
    input_tokens: int, output_tokens: int, cost_usd: float,
    item_id: int | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO api_costs (provider, model, input_tokens, output_tokens, cost_usd, item_id)
               VALUES (?,?,?,?,?,?)""",
            (provider, model, input_tokens, output_tokens, cost_usd, item_id),
        )
        await db.commit()

async def get_monthly_cost(db_path: str, provider: str) -> float:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs
               WHERE provider = ?
               AND strftime('%Y-%m', recorded_at) = strftime('%Y-%m', 'now')""",
            (provider,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

_JSON_FIELDS = ("tags", "key_points", "sections", "main_arguments",
                "insights", "questions_raised", "related_concepts", "ai_models")

def _parse_row(row: dict) -> dict:
    for field in _JSON_FIELDS:
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return row

async def list_notes(
    db_path: str,
    topic: str | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[dict]:
    query = "SELECT * FROM items WHERE 1=1"
    params: list = []
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if search:
        query += " AND (title LIKE ? OR summary LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if tags:
        for tag in tags:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [_parse_row(dict(r)) for r in rows]

async def upgrade_to_detailed(
    db_path: str, note_id: int, result: SummaryResult
) -> SummaryResult:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE items SET
               summary_mode='detailed',
               main_arguments=?, insights=?, questions_raised=?,
               related_concepts=?, api_cost_usd=api_cost_usd+?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                json.dumps(result.main_arguments or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                json.dumps(result.related_concepts or [], ensure_ascii=False),
                result.cost_usd, note_id,
            )
        )
        await db.commit()
    return result

async def get_topics(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT topic, COUNT(*) as count FROM items WHERE topic IS NOT NULL GROUP BY topic ORDER BY count DESC"
        )
        rows = await cursor.fetchall()
    return [{"topic": r[0], "count": r[1]} for r in rows]

async def get_random_notes(db_path: str, n: int = 4) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM items ORDER BY RANDOM() LIMIT ?", (n,)
        )
        rows = await cursor.fetchall()
    return [_parse_row(dict(r)) for r in rows]
