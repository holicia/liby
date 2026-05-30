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

async def _project_name(db, project_id: int | None) -> str | None:
    if project_id is None:
        return None
    cursor = await db.execute("SELECT name FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    return row[0] if row else None

def _make_md_content(
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_name: str | None = None,
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "{result.title}"',
        f"type: {source_type}",
        f"source: {source_url}",
        f"tags: {json.dumps(result.tags, ensure_ascii=False)}",
        f"topic: {result.suggested_topic}",
        *([f"project: {project_name}"] if project_name else []),
        f"ai_provider: {ai_provider}",
        f"summary_mode: {result.summary_mode}",
        f"created: {today}",
        "---",
        "",
    ]

    def _ts(sec: int) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    lines += ["## 요약", result.summary, ""]

    if result.sections:  # detailed 계층 본문
        lines.append("## 목차")
        for sec in result.sections:
            lines.append(f"- {sec['heading']}")
            for sub in sec.get("subsections", []):
                lines.append(f"  - {sub['heading']}")
        lines.append("")
        for sec in result.sections:
            lines += [f"## {sec['heading']}", ""]
            for sub in sec.get("subsections", []):
                lines += [f"### {sub['heading']}", ""]
                for it in sub.get("items", []):
                    if "text" in it:  # 신규: 문단 + 인용 (text 키가 있으면 신규 스키마)
                        if it["text"]:
                            lines.append(it["text"])
                        if it.get("quote"):
                            ts = f"[{_ts(it['t'])}] " if "t" in it else ""
                            lines.append(f'> {ts}"{it["quote"]}"')
                    else:  # 백워드 호환: 옛 {lead, bullets}
                        ts = f" ({_ts(it['t'])})" if "t" in it else ""
                        lines.append(f"- **{it.get('lead','')}**{ts}")
                        for b in it.get("bullets", []):
                            lines.append(f"  - {b}")
                    lines.append("")
    elif result.paragraphs:  # quick 신규: 문단 본문
        lines.append("## 본문")
        lines.append("")
        for p in result.paragraphs:
            lines.append(p["text"])
            if p.get("quote"):
                ts = f"[{_ts(p['t'])}] " if "t" in p else ""
                lines.append(f'> {ts}"{p["quote"]}"')
            lines.append("")
    else:  # 백워드 호환: 옛 quick key_points
        lines.append("## 핵심 포인트")
        for p in result.key_points:
            lines.append(f"- {p}")

    def _heading(title: str) -> None:
        if lines and lines[-1] != "":  # 직전이 빈 줄이 아니면 한 줄만 띄움(이중 빈 줄 방지)
            lines.append("")
        lines.append(title)

    if result.insights:
        _heading("## 인사이트")
        for i in result.insights:
            lines.append(f"- {i}")
    if result.questions_raised:
        _heading("## 탐구할 질문")
        for q in result.questions_raised:
            lines.append(f"- {q}")
    return "\n".join(lines)

async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_id: int | None = None,
    timeline: list | None = None,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-{_safe_filename(result.title)}.md"
    subdir = os.path.join(vault_path, source_type)
    os.makedirs(subdir, exist_ok=True)
    md_path = os.path.join(subdir, filename)

    async with aiosqlite.connect(db_path) as db:
        proj_name = await _project_name(db, project_id)
        md_content = _make_md_content(source_type, source_url, result, ai_provider, proj_name)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        cursor = await db.execute(
            """INSERT INTO items
               (type, title, source_url, summary, key_points, sections, tags, topic,
                summary_mode, insights, questions_raised,
                ai_provider, ai_models, api_cost_usd, md_file_path, project_id,
                timeline, paragraphs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, result.title, source_url, result.summary,
                json.dumps(result.key_points, ensure_ascii=False),
                json.dumps(result.sections, ensure_ascii=False),
                json.dumps(result.tags, ensure_ascii=False),
                result.suggested_topic, result.summary_mode,
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
                ai_provider,
                json.dumps(result.models_used, ensure_ascii=False),
                result.cost_usd, md_path, project_id,
                json.dumps(timeline or [], ensure_ascii=False),
                json.dumps(result.paragraphs or [], ensure_ascii=False),
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

_JSON_FIELDS = ("tags", "key_points", "sections",
                "insights", "questions_raised", "ai_models", "timeline", "paragraphs")

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
    project_id: int | str | None = None,
    limit: int = 50,
) -> list[dict]:
    query = "SELECT * FROM items WHERE 1=1"
    params: list = []
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if project_id == "none":
        query += " AND project_id IS NULL"
    elif project_id is not None:
        query += " AND project_id = ?"
        params.append(int(project_id))
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
               sections=?,
               paragraphs=COALESCE(NULLIF(?, '[]'), paragraphs),
               insights=?, questions_raised=?,
               api_cost_usd=api_cost_usd+?,
               updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                json.dumps(result.sections or [], ensure_ascii=False),
                json.dumps(result.paragraphs or [], ensure_ascii=False),
                json.dumps(result.insights or [], ensure_ascii=False),
                json.dumps(result.questions_raised or [], ensure_ascii=False),
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


def _set_md_project(md_path: str, project_name: str) -> None:
    """기존 .md frontmatter의 project: 줄을 갱신/삽입(이름 있을 때) 또는 제거(빈 이름)."""
    if not md_path or not os.path.exists(md_path):
        return
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return
    existing = next((i for i in range(1, end) if lines[i].startswith("project:")), None)
    if not project_name:
        if existing is None:
            return  # 제거할 줄이 없으면 파일 쓰기 생략
        del lines[existing]
    else:
        new_line = f"project: {project_name}"
        if existing is not None:
            lines[existing] = new_line
        else:
            insert_at = next((i for i in range(1, end) if lines[i].startswith("topic:")), end - 1)
            lines.insert(insert_at + 1, new_line)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def create_project(db_path: str, name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("프로젝트 이름은 비어 있을 수 없습니다.")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("INSERT INTO projects (name) VALUES (?)", (name,))
        await db.commit()
        return cursor.lastrowid


async def list_projects(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """SELECT p.id, p.name, COUNT(i.id) AS count
               FROM projects p LEFT JOIN items i ON i.project_id = p.id
               GROUP BY p.id, p.name ORDER BY p.name"""
        )
        rows = await cursor.fetchall()
    return [{"id": r[0], "name": r[1], "count": r[2]} for r in rows]


async def unassigned_count(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM items WHERE project_id IS NULL")
        return (await cursor.fetchone())[0]


async def set_note_project(db_path: str, note_id: int, project_id: int | None) -> None:
    async with aiosqlite.connect(db_path) as db:
        name = await _project_name(db, project_id) or ""
        cursor = await db.execute("SELECT md_file_path FROM items WHERE id = ?", (note_id,))
        row = await cursor.fetchone()
        if row and row[0]:
            _set_md_project(row[0], name)  # 파일 먼저 동기화 후 커밋 (save_note 패턴)
        await db.execute(
            "UPDATE items SET project_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (project_id, note_id),
        )
        await db.commit()


async def rename_project(db_path: str, project_id: int, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("프로젝트 이름은 비어 있을 수 없습니다.")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT md_file_path FROM items WHERE project_id = ?", (project_id,))
        paths = [r[0] for r in await cursor.fetchall()]
        for p in paths:
            if p:
                _set_md_project(p, name)
        await db.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
        await db.commit()


async def delete_project(db_path: str, project_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT md_file_path FROM items WHERE project_id = ?", (project_id,))
        paths = [r[0] for r in await cursor.fetchall()]
        for p in paths:
            if p:
                _set_md_project(p, "")
        await db.execute("UPDATE items SET project_id = NULL WHERE project_id = ?", (project_id,))
        await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()


async def set_timeline(db_path: str, note_id: int, chapters: list) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE items SET timeline = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(chapters or [], ensure_ascii=False), note_id),
        )
        await db.commit()
