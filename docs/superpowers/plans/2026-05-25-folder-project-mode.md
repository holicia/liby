# 폴더/프로젝트 모드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 수동 관리하는 "프로젝트(폴더)" 조직 축을 추가해, 사이드바에서 주제별/프로젝트별 모드를 전환하고 노트를 프로젝트에 배정·재배정할 수 있게 한다.

**Architecture:** `projects` 테이블 + `items.project_id`(단일 소속, NULL=미분류)를 추가한다. 저장 계층(storage.py)에 프로젝트 CRUD와 필터를 넣고, 신규 `routers/projects.py`와 기존 라우터 확장으로 API를 제공한다. 프론트는 사이드바 모드 토글 + 공유 "현재 프로젝트" 드롭다운 + 노트 카드 재배정 셀렉트로 구성한다. vault 디렉토리 구조는 type별로 유지하고 프로젝트는 .md frontmatter `project:` 줄로만 기록한다.

**Tech Stack:** FastAPI, HTMX, Jinja2, Tailwind(CDN), aiosqlite(SQLite), pytest + pytest-asyncio + httpx(ASGITransport).

---

## 파일 구조 (생성/수정)

| 파일 | 역할 | 변경 |
|------|------|------|
| `models.py` | 스키마/마이그레이션 | `projects` 테이블 + `items.project_id` ALTER |
| `services/storage.py` | 저장/조회 + 프로젝트 CRUD | 함수 추가/수정 |
| `routers/projects.py` | 프로젝트 API | **신규** |
| `routers/items.py` | 노트 목록 필터 + 재배정 | 수정 |
| `routers/youtube.py`,`pdf.py`,`code.py`,`text.py` | 입력 시 project_id 전달 | 수정 |
| `main.py` | projects 라우터 등록 | 수정 |
| `templates/partials/sidebar_projects.html` | 프로젝트별 사이드바 목록 | **신규** |
| `templates/partials/project_options.html` | 공유 드롭다운 옵션 | **신규** |
| `templates/partials/note_card.html` | 프로젝트 재배정 셀렉트 | 수정 |
| `templates/base.html` | 모드 토글 + 공유 드롭다운 + JS | 수정 |
| `templates/index.html` | (영향 없음, 참고만) | - |
| `tests/test_models.py`,`test_storage.py`,`test_routes_items.py` | 테스트 | 추가 |
| `tests/test_routes_projects.py` | 프로젝트 라우터 테스트 | **신규** |

**테스트 실행 (Windows):** `python -m pytest <경로>::<테스트> -v`

---

## Task 1: DB 마이그레이션 (projects 테이블 + items.project_id)

**Files:**
- Modify: `models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_models.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_init_db_creates_projects_table(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_adds_project_id_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "project_id" in cols


@pytest.mark.asyncio
async def test_init_db_migrates_existing_items_table(tmp_path):
    # project_id 컬럼이 없는 구버전 items 테이블을 만든 뒤 init_db가 추가하는지
    db_path = str(tmp_path / "test.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, title TEXT NOT NULL)"
        )
        await db.commit()
    await init_db(db_path)  # 멱등 + ALTER 수행
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
    assert "project_id" in cols
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_models.py -v`
Expected: 새 테스트 3개 FAIL (projects 테이블/컬럼 없음)

- [ ] **Step 3: 최소 구현** — `models.py` 수정

`CREATE_API_COSTS` 정의 아래에 추가:
```python
CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


async def _ensure_project_id_column(db) -> None:
    cursor = await db.execute("PRAGMA table_info(items)")
    cols = [r[1] for r in await cursor.fetchall()]
    if "project_id" not in cols:
        await db.execute("ALTER TABLE items ADD COLUMN project_id INTEGER")
```

`init_db`를 다음으로 교체:
```python
async def init_db(db_path: str = config.DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_ITEMS)
        await db.execute(CREATE_SETTINGS)
        await db.execute(CREATE_API_COSTS)
        await db.execute(CREATE_PROJECTS)
        await _ensure_project_id_column(db)
        await db.commit()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (기존 3개 + 신규 3개)

- [ ] **Step 5: 커밋**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add projects table and items.project_id migration"
```

---

## Task 2: 저장 계층 — save_note에 project_id + frontmatter, list_notes 필터

**Files:**
- Modify: `services/storage.py` (`_make_md_content` 13-49, `save_note` 51-89, `list_notes` 134-160)
- Test: `tests/test_storage.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_storage.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_save_note_with_project_id(db, tmp_path):
    # 먼저 프로젝트 생성
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO projects (name) VALUES ('회사 리서치')")
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE name='회사 리서치'")
        pid = (await cur.fetchone())[0]

    result = make_result()
    note_id = await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="https://youtube.com/watch?v=abc",
        result=result, ai_provider="claude", project_id=pid,
    )
    note = await get_note(db, note_id)
    assert note["project_id"] == pid


@pytest.mark.asyncio
async def test_save_note_writes_project_in_frontmatter(db, tmp_path):
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO projects (name) VALUES ('회사 리서치')")
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE name='회사 리서치'")
        pid = (await cur.fetchone())[0]

    await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="u", result=make_result(),
        ai_provider="claude", project_id=pid,
    )
    md = next((tmp_path / "vault" / "youtube").glob("*.md"))
    content = md.read_text(encoding="utf-8")
    assert "project: 회사 리서치" in content


@pytest.mark.asyncio
async def test_list_notes_filters_by_project_id(db, tmp_path):
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO projects (name) VALUES ('P1')")
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE name='P1'")
        pid = (await cur.fetchone())[0]
    vault = str(tmp_path / "vault")
    await save_note(db_path=db, vault_path=vault, source_type="youtube",
                    source_url="u1", result=make_result(), ai_provider="claude", project_id=pid)
    await save_note(db_path=db, vault_path=vault, source_type="youtube",
                    source_url="u2", result=make_result(), ai_provider="claude")  # 미분류

    in_p = await list_notes(db, project_id=pid)
    assert len(in_p) == 1
    unassigned = await list_notes(db, project_id="none")
    assert len(unassigned) == 1
```

`tests/test_storage.py` 상단 import에 `list_notes` 추가:
```python
from services.storage import save_note, get_note, record_api_cost, get_monthly_cost, list_notes
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: 새 테스트 3개 FAIL (`save_note() got unexpected keyword 'project_id'` 등)

- [ ] **Step 3: 최소 구현** — `services/storage.py`

(3a) `_make_md_content` 시그니처와 frontmatter 수정 — `project_name` 인자 추가, `topic:` 줄 아래에 `project:` 추가:
```python
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
        f"project: {project_name or ''}",
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
```

(3b) `_make_md_content` 위(예: `_safe_filename` 아래)에 프로젝트명 조회 헬퍼 추가:
```python
async def _project_name(db, project_id: int | None) -> str | None:
    if project_id is None:
        return None
    cursor = await db.execute("SELECT name FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    return row[0] if row else None
```

(3c) `save_note`에 `project_id` 추가 — 시그니처, frontmatter 호출, INSERT 모두 수정:
```python
async def save_note(
    db_path: str, vault_path: str,
    source_type: str, source_url: str,
    result: SummaryResult, ai_provider: str,
    project_id: int | None = None,
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
                summary_mode, main_arguments, insights, questions_raised,
                related_concepts, ai_provider, ai_models, api_cost_usd, md_file_path, project_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                result.cost_usd, md_path, project_id,
            )
        )
        await db.commit()
        return cursor.lastrowid
```

(3d) `list_notes`에 `project_id` 필터 추가:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS (기존 + 신규 3개). 기존 `test_save_note_creates_md_file`도 통과(기본 project_id=None).

- [ ] **Step 5: 커밋**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: save_note accepts project_id, list_notes filters by project"
```

---

## Task 3: 저장 계층 — 프로젝트 CRUD + 재배정 + frontmatter 패치

**Files:**
- Modify: `services/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_storage.py` 끝에 추가

```python
from services.storage import (
    create_project, list_projects, rename_project, delete_project,
    unassigned_count, set_note_project,
)

@pytest.mark.asyncio
async def test_create_and_list_projects(db):
    pid = await create_project(db, "회사 리서치")
    assert pid > 0
    projects = await list_projects(db)
    assert any(p["id"] == pid and p["name"] == "회사 리서치" and p["count"] == 0 for p in projects)


@pytest.mark.asyncio
async def test_create_project_duplicate_raises(db):
    await create_project(db, "P")
    with pytest.raises(Exception):
        await create_project(db, "P")


@pytest.mark.asyncio
async def test_list_projects_counts_notes(db, tmp_path):
    pid = await create_project(db, "P1")
    await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                    source_url="u", result=make_result(), ai_provider="claude", project_id=pid)
    projects = await list_projects(db)
    assert next(p for p in projects if p["id"] == pid)["count"] == 1


@pytest.mark.asyncio
async def test_unassigned_count(db, tmp_path):
    await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                    source_url="u", result=make_result(), ai_provider="claude")
    assert await unassigned_count(db) == 1


@pytest.mark.asyncio
async def test_set_note_project_updates_db_and_frontmatter(db, tmp_path):
    pid = await create_project(db, "P1")
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    await set_note_project(db, nid, pid)
    note = await get_note(db, nid)
    assert note["project_id"] == pid
    content = open(note["md_file_path"], encoding="utf-8").read()
    assert "project: P1" in content


@pytest.mark.asyncio
async def test_rename_project_updates_frontmatter(db, tmp_path):
    pid = await create_project(db, "Old")
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", project_id=pid)
    await rename_project(db, pid, "New")
    projects = await list_projects(db)
    assert next(p for p in projects if p["id"] == pid)["name"] == "New"
    content = open((await get_note(db, nid))["md_file_path"], encoding="utf-8").read()
    assert "project: New" in content


@pytest.mark.asyncio
async def test_delete_project_unassigns_notes(db, tmp_path):
    pid = await create_project(db, "P1")
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", project_id=pid)
    await delete_project(db, pid)
    assert (await get_note(db, nid))["project_id"] is None
    assert all(p["id"] != pid for p in await list_projects(db))
    content = open((await get_note(db, nid))["md_file_path"], encoding="utf-8").read()
    assert "project: \n" in content or "project:\n" in content
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: 새 테스트 FAIL (`cannot import name 'create_project'`)

- [ ] **Step 3: 최소 구현** — `services/storage.py` 끝에 추가

```python
def _set_md_project(md_path: str, project_name: str) -> None:
    """기존 .md 파일의 frontmatter에서 project: 줄을 갱신(없으면 topic: 아래에 삽입)."""
    if not md_path or not os.path.exists(md_path):
        return
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    # frontmatter 범위: 첫 '---' ~ 두 번째 '---'
    if not lines or lines[0].strip() != "---":
        return
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return
    new_line = f"project: {project_name}"
    replaced = False
    for i in range(1, end):
        if lines[i].startswith("project:"):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        insert_at = next((i for i in range(1, end) if lines[i].startswith("topic:")), end)
        lines.insert(insert_at + 1, new_line)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def create_project(db_path: str, name: str) -> int:
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
        await db.execute("UPDATE items SET project_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (project_id, note_id))
        await db.commit()
        name = await _project_name(db, project_id) or ""
        cursor = await db.execute("SELECT md_file_path FROM items WHERE id = ?", (note_id,))
        row = await cursor.fetchone()
    if row and row[0]:
        _set_md_project(row[0], name)


async def rename_project(db_path: str, project_id: int, name: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
        await db.commit()
        cursor = await db.execute("SELECT md_file_path FROM items WHERE project_id = ?", (project_id,))
        paths = [r[0] for r in await cursor.fetchall()]
    for p in paths:
        _set_md_project(p, name)


async def delete_project(db_path: str, project_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT md_file_path FROM items WHERE project_id = ?", (project_id,))
        paths = [r[0] for r in await cursor.fetchall()]
        await db.execute("UPDATE items SET project_id = NULL WHERE project_id = ?", (project_id,))
        await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()
    for p in paths:
        _set_md_project(p, "")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add services/storage.py tests/test_storage.py
git commit -m "feat: project CRUD, reassignment, and frontmatter sync in storage"
```

---

## Task 4: 프로젝트 API 라우터 + 사이드바 partial

**Files:**
- Create: `routers/projects.py`, `templates/partials/sidebar_projects.html`, `templates/partials/project_options.html`
- Modify: `main.py:17-23`
- Test: `tests/test_routes_projects.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_routes_projects.py`

```python
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_get_projects_renders_list():
    with patch("routers.projects.list_projects", return_value=[{"id": 1, "name": "회사 리서치", "count": 2}]), \
         patch("routers.projects.unassigned_count", return_value=3):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/projects")
    assert resp.status_code == 200
    assert "회사 리서치" in resp.text
    assert "미분류" in resp.text


@pytest.mark.asyncio
async def test_post_project_creates():
    with patch("routers.projects.create_project", return_value=1) as mock_create, \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/projects", data={"name": "새 프로젝트"})
    assert resp.status_code == 200
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_delete_project():
    with patch("routers.projects.delete_project") as mock_del, \
         patch("routers.projects.list_projects", return_value=[]), \
         patch("routers.projects.unassigned_count", return_value=0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/projects/5")
    assert resp.status_code == 200
    mock_del.assert_called_once()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_routes_projects.py -v`
Expected: FAIL (404 — 라우터 없음)

- [ ] **Step 3: 구현**

(3a) `templates/partials/project_options.html` (공유 드롭다운 옵션 — Task 7에서 사용):
```html
<option value="">(프로젝트 없음)</option>
{% for p in projects %}
<option value="{{ p.id }}">{{ p.name }}</option>
{% endfor %}
```

(3b) `templates/partials/sidebar_projects.html`:
```html
<a onclick="enterHomeView()"
   class="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-gray-500 dark:text-gray-400 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] dark:hover:bg-[#14291E] dark:hover:text-[#34A66A] cursor-pointer transition-colors">
  <span class="w-2 h-2 rounded-full bg-[#1F6F4A]"></span>전체 노트
</a>
{% for p in projects %}
<div class="group flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-gray-500 dark:text-gray-400 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] dark:hover:bg-[#14291E] dark:hover:text-[#34A66A] cursor-pointer transition-colors">
  <span class="flex items-center gap-2 flex-1 min-w-0" onclick="enterProjectView('{{ p.id }}', '{{ p.name }}')">
    <span class="w-2 h-2 rounded-full bg-amber-400"></span>
    <span class="truncate">{{ p.name }}</span>
    <span class="ml-auto text-gray-400 text-[11px]">{{ p.count }}</span>
  </span>
  <button class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-[#1F6F4A]"
          title="이름 변경"
          onclick="renameProject('{{ p.id }}', '{{ p.name }}')">✎</button>
  <button class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500"
          title="삭제"
          onclick="deleteProject('{{ p.id }}', '{{ p.name }}')">✕</button>
</div>
{% endfor %}
<a onclick="enterUnassignedView()"
   class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-gray-500 dark:text-gray-400 hover:bg-[#EAF4EE] hover:text-[#1F6F4A] dark:hover:bg-[#14291E] dark:hover:text-[#34A66A] cursor-pointer transition-colors">
  <span class="w-2 h-2 rounded-full bg-gray-300"></span>미분류
  <span class="ml-auto text-gray-400 text-[11px]">{{ unassigned }}</span>
</a>
<button class="w-full text-center text-xs text-gray-400 border border-dashed border-[#E2E8E4] rounded-lg py-1.5 mt-1 hover:border-[#1F6F4A] hover:text-[#1F6F4A] transition-colors"
        onclick="createProject()">+ 새 프로젝트</button>
```

(3c) `routers/projects.py`:
```python
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
import config
from services.storage import (
    list_projects, unassigned_count, create_project, rename_project, delete_project,
)
from templates_env import templates

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _render_list(request: Request) -> HTMLResponse:
    projects = await list_projects(config.DB_PATH)
    unassigned = await unassigned_count(config.DB_PATH)
    resp = templates.TemplateResponse(
        request, "partials/sidebar_projects.html",
        {"projects": projects, "unassigned": unassigned},
    )
    resp.headers["HX-Trigger"] = "projectsChanged"
    return resp


@router.get("")
async def get_projects(request: Request):
    return await _render_list(request)


@router.get("/options")
async def get_project_options(request: Request):
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(request, "partials/project_options.html", {"projects": projects})


@router.post("")
async def add_project(request: Request, name: str = Form(...)):
    name = name.strip()
    if name:
        try:
            await create_project(config.DB_PATH, name)
        except Exception:
            pass  # 중복 등은 무시하고 목록 재렌더
    return await _render_list(request)


@router.patch("/{project_id}")
async def edit_project(request: Request, project_id: int, name: str = Form(...)):
    name = name.strip()
    if name:
        await rename_project(config.DB_PATH, project_id, name)
    return await _render_list(request)


@router.delete("/{project_id}")
async def remove_project(request: Request, project_id: int):
    await delete_project(config.DB_PATH, project_id)
    return await _render_list(request)
```

(3d) `main.py` 라우터 등록 — import 줄과 include 추가:
```python
from routers import youtube, pdf, items, settings, code, tasks, text, projects
app.include_router(youtube.router)
app.include_router(pdf.router)
app.include_router(items.router)
app.include_router(settings.router)
app.include_router(code.router)
app.include_router(tasks.router)
app.include_router(text.router)
app.include_router(projects.router)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_routes_projects.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add routers/projects.py templates/partials/sidebar_projects.html templates/partials/project_options.html main.py tests/test_routes_projects.py
git commit -m "feat: projects API router and sidebar partial"
```

---

## Task 5: items 라우터 — 프로젝트 필터 + 재배정 엔드포인트

**Files:**
- Modify: `routers/items.py` (`get_items` 15-26, 신규 엔드포인트 추가)
- Test: `tests/test_routes_items.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_routes_items.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_get_items_with_project_filter():
    with patch("routers.items.list_notes", return_value=[MOCK_NOTE]) as mock_list, \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items?project_id=3")
    assert resp.status_code == 200
    assert mock_list.call_args.kwargs.get("project_id") == "3"


@pytest.mark.asyncio
async def test_set_note_project():
    with patch("routers.items.set_note_project") as mock_set, \
         patch("routers.items.get_note", return_value=MOCK_NOTE), \
         patch("routers.items.list_projects", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/1/project", data={"project_id": "5"})
    assert resp.status_code == 200
    mock_set.assert_called_once()
    # 빈 값이면 None으로 해제
    assert mock_set.call_args.args[2] == 5
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_routes_items.py -v`
Expected: 새 테스트 2개 FAIL

- [ ] **Step 3: 구현** — `routers/items.py`

import 수정 (storage import 블록에 추가):
```python
from services.storage import (
    get_note, list_notes, upgrade_to_detailed,
    record_api_cost, get_topics, get_random_notes,
    list_projects, set_note_project,
)
```

`get_items` 수정 — `project_id` 쿼리 추가 + projects 컨텍스트:
```python
@router.get("")
async def get_items(
    request: Request,
    topic: Optional[str] = Query(None),
    tags: list[str] = Query([]),
    search: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
):
    notes = await list_notes(config.DB_PATH, topic=topic, tags=tags, search=search, project_id=project_id)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes, "projects": projects},
    )
```

`get_random_notes_partial`도 projects 컨텍스트 추가 (note_card가 projects 참조하므로):
```python
@router.get("/random")
async def get_random_notes_partial(request: Request):
    notes = await get_random_notes(config.DB_PATH, n=4)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_list.html",
        {"notes": notes, "projects": projects},
    )
```

신규 재배정 엔드포인트 (`get_item` 위, `/{note_id}` 라우트보다 먼저 정의해 경로 충돌 방지):
```python
@router.post("/{note_id}/project")
async def set_item_project(request: Request, note_id: int, project_id: str = Form("")):
    pid = int(project_id) if project_id.strip() else None
    await set_note_project(config.DB_PATH, note_id, pid)
    note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_card.html", {"note": note, "projects": projects},
    )
```

`upgrade_note`도 projects 컨텍스트 추가 (note_card 반환하므로) — 마지막 return 수정:
```python
    updated_note = await get_note(config.DB_PATH, note_id)
    projects = await list_projects(config.DB_PATH)
    return templates.TemplateResponse(
        request, "partials/note_card.html",
        {"note": updated_note, "projects": projects},
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_routes_items.py -v`
Expected: PASS (기존 + 신규 2개)

- [ ] **Step 5: 커밋**

```bash
git add routers/items.py tests/test_routes_items.py
git commit -m "feat: project filter on item list and note reassignment endpoint"
```

---

## Task 6: 입력 라우터에 project_id 전달 (youtube/pdf/code/text)

**Files:**
- Modify: `routers/youtube.py`, `routers/pdf.py`, `routers/code.py`, `routers/text.py`
- Test: `tests/test_routes_youtube.py`

각 라우터의 `@router.post("")` 핸들러에 `project_id` 폼 파라미터를 받아 `do_work` 안의 `save_note(...)` 호출에 전달한다. 4개 파일 모두 동일 패턴.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_routes_youtube.py` 끝에 추가

```python
@pytest.mark.asyncio
async def test_youtube_accepts_project_id():
    captured = {}

    async def fake_enqueue(task, fn):
        captured["fn"] = fn  # 실제 실행은 하지 않고 폼 수신만 검증

    with patch("routers.youtube.enqueue", side_effect=fake_enqueue), \
         patch("routers.youtube.get_provider"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/youtube", data={
                "url": "https://youtu.be/abc", "provider": "claude",
                "mode": "quick", "project_id": "7",
            })
    assert resp.status_code == 200
```

> 참고: 기존 `tests/test_routes_youtube.py`의 enqueue/모킹 패턴을 따른다. 핵심은 `project_id` 폼 필드가 있어도 200을 반환하는지(파라미터 시그니처 수용) 확인하는 것이다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_routes_youtube.py -v`
Expected: 신규 테스트 FAIL 또는 422(project_id 미수용) — 현재 시그니처에 따라 다름

- [ ] **Step 3: 구현** — 4개 라우터 동일 수정

`routers/youtube.py` `analyze_youtube` 시그니처에 추가:
```python
async def analyze_youtube(
    request: Request,
    url: str = Form(...),
    provider: str = Form(config.DEFAULT_AI_PROVIDER),
    mode: str = Form("quick"),
    project_id: str = Form(""),
):
    pid = int(project_id) if project_id.strip() else None
    task = new_task("youtube", url)
    ai = get_provider(provider)
```
그리고 `do_work` 안의 `save_note(...)` 호출에 `project_id=pid` 추가:
```python
        note_id = await save_note(
            db_path=config.DB_PATH, vault_path=config.VAULT_PATH,
            source_type="youtube", source_url=url,
            result=result, ai_provider=ai.name(), project_id=pid,
        )
```

`routers/pdf.py` — 동일하게 `project_id: str = Form("")` 추가, `pid` 계산, `save_note(..., project_id=pid)`.
`routers/code.py` — 동일.
`routers/text.py` — 동일.

(4개 모두: 시그니처에 `project_id: str = Form("")` 추가 → 함수 본문 시작부에 `pid = int(project_id) if project_id.strip() else None` → 해당 `save_note` 호출에 `project_id=pid` 추가.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_routes_youtube.py tests/test_routes_pdf.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add routers/youtube.py routers/pdf.py routers/code.py routers/text.py tests/test_routes_youtube.py
git commit -m "feat: input routers pass project_id to save_note"
```

---

## Task 7: 프론트엔드 — 사이드바 모드 토글, 공유 드롭다운, 카드 재배정

**Files:**
- Modify: `templates/base.html`, `templates/partials/note_card.html`
- 검증: 수동(브라우저) — 이 프로젝트는 HTMX/JS UI라 단위 테스트 대신 dev 서버로 확인

- [ ] **Step 1: note_card.html에 프로젝트 셀렉트 추가**

`note_card.html`의 버튼 묶음(`<div class="flex flex-col gap-1 flex-shrink-0">`) 안, "전체 보기" 버튼 위에 추가:
```html
    <select name="project_id"
            class="text-[10px] bg-white border border-[#E2E8E4] rounded px-1.5 py-1 text-gray-500 dark:bg-gray-700 dark:text-gray-300 max-w-[110px]"
            hx-post="/api/items/{{ note.id }}/project"
            hx-trigger="change"
            hx-target="closest .note-card"
            hx-swap="outerHTML">
      <option value="" {% if not note.project_id %}selected{% endif %}>미분류</option>
      {% for p in projects %}
      <option value="{{ p.id }}" {% if note.project_id == p.id %}selected{% endif %}>{{ p.name }}</option>
      {% endfor %}
    </select>
```
> `projects`가 컨텍스트에 없을 때(예외 상황)도 안전하도록 `{% for p in projects or [] %}`로 두어도 된다. Task 5에서 note_card를 렌더하는 모든 경로에 `projects`를 전달하므로 정상 케이스에선 항상 존재한다.

- [ ] **Step 2: base.html — 사이드바 모드 토글 + 동적 목록 영역**

기존 사이드바의 "전체 노트" 링크 ~ "+ 새 주제 추가" 버튼 영역을 다음 구조로 교체. 모드 토글을 최상단에 두고, 토글 아래에 모드별 목록 컨테이너 2개(`#topic-mode`, `#project-mode`)를 둔다. `#topic-mode`는 기존 내용(전체 노트 링크 + 주제별 목록 + 새 주제 버튼) 유지, `#project-mode`는 숨김 상태로 시작하며 `/api/projects`를 로드.

```html
    <!-- 모드 토글 -->
    <div class="flex gap-1 p-1 mb-2 bg-[#F3F5F4] dark:bg-gray-800 rounded-lg text-[11px]">
      <button id="mode-topic-btn" onclick="setSidebarMode('topic')"
              class="flex-1 py-1 rounded-md font-semibold bg-white text-[#1F6F4A] dark:bg-gray-700 dark:text-[#34A66A]">주제별</button>
      <button id="mode-project-btn" onclick="setSidebarMode('project')"
              class="flex-1 py-1 rounded-md text-gray-500 dark:text-gray-400">프로젝트별</button>
    </div>

    <!-- 주제별 모드 (기존) -->
    <div id="topic-mode">
      <a id="all-notes-link" onclick="enterHomeView()"
         class="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#EAF4EE] text-[#1F6F4A] dark:bg-[#14291E] dark:text-[#34A66A] font-semibold text-xs cursor-pointer">
        <span class="w-2 h-2 rounded-full bg-[#1F6F4A]"></span>전체 노트
        <span class="ml-auto bg-[#1F6F4A] text-white text-[10px] px-2 py-0.5 rounded-full font-bold" id="total-count">0</span>
      </a>
      <p class="text-[10px] font-bold uppercase tracking-widest text-gray-400 px-2 pt-3 pb-1">주제별</p>
      <div id="topic-list" hx-get="/api/items/topics" hx-trigger="load" hx-swap="innerHTML"></div>
      <button class="w-full text-center text-xs text-gray-400 border border-dashed border-[#E2E8E4] rounded-lg py-1.5 mt-1 hover:border-[#1F6F4A] hover:text-[#1F6F4A] transition-colors"
              onclick="promptNewTopic()">+ 새 주제 추가</button>
    </div>

    <!-- 프로젝트별 모드 -->
    <div id="project-mode" class="hidden"
         hx-get="/api/projects" hx-trigger="load, projectsChanged from:body" hx-swap="innerHTML"></div>
```

- [ ] **Step 3: base.html — 공유 "현재 프로젝트" 드롭다운**

`#input-panel` div **밖**(바로 아래)에 추가 — 탭 전환 시 사라지지 않도록:
```html
<div class="bg-[#EAF4EE] dark:bg-[#14291E] border-b border-[#E2E8E4] dark:border-gray-700 px-5 py-1.5 flex items-center gap-2">
  <span class="text-[11px] text-gray-500 dark:text-gray-400">현재 프로젝트</span>
  <select id="current-project" name="project_id"
          class="text-xs bg-white border border-[#E2E8E4] rounded-lg px-2 py-1 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
          hx-get="/api/projects/options" hx-trigger="load, projectsChanged from:body" hx-swap="innerHTML">
    <option value="">(프로젝트 없음)</option>
  </select>
</div>
```

각 입력 폼(`input_youtube.html`, `input_pdf.html`, `input_code.html`, `input_text.html`)의 `<form ...>` 태그에 `hx-include="#current-project"` 추가. 예: input_youtube.html:
```html
<form hx-post="/api/youtube" hx-target="#queue-panel" hx-swap="beforeend" hx-include="#current-project" class="flex gap-2 items-center">
```
(pdf는 기존 `hx-include`가 없으므로 추가; 4개 폼 모두 `hx-include="#current-project"` 추가.)

- [ ] **Step 4: base.html — JS 함수 추가**

기존 `<script>` 블록의 `enterHomeView()` 다음에 추가:
```javascript
function setSidebarMode(mode) {
  const topic = document.getElementById('topic-mode');
  const project = document.getElementById('project-mode');
  const tb = document.getElementById('mode-topic-btn');
  const pb = document.getElementById('mode-project-btn');
  const on = ['bg-white','text-[#1F6F4A]','dark:bg-gray-700','dark:text-[#34A66A]','font-semibold'];
  const off = ['text-gray-500','dark:text-gray-400'];
  if (mode === 'project') {
    topic.classList.add('hidden'); project.classList.remove('hidden');
    pb.classList.add(...on); pb.classList.remove(...off);
    tb.classList.remove(...on); tb.classList.add(...off);
  } else {
    project.classList.add('hidden'); topic.classList.remove('hidden');
    tb.classList.add(...on); tb.classList.remove(...off);
    pb.classList.remove(...on); pb.classList.add(...off);
  }
}
function enterProjectView(id, name) {
  const label = document.getElementById('section-label');
  if (label) label.textContent = name;
  const rec = document.getElementById('recommended-section');
  if (rec) rec.style.display = 'none';
  htmx.ajax('GET', `/api/items?project_id=${encodeURIComponent(id)}`, { target: '#note-list', swap: 'innerHTML' });
}
function enterUnassignedView() {
  const label = document.getElementById('section-label');
  if (label) label.textContent = '미분류';
  const rec = document.getElementById('recommended-section');
  if (rec) rec.style.display = 'none';
  htmx.ajax('GET', '/api/items?project_id=none', { target: '#note-list', swap: 'innerHTML' });
}
function createProject() {
  const name = prompt('새 프로젝트 이름:');
  if (name && name.trim()) {
    htmx.ajax('POST', '/api/projects', { target: '#project-mode', swap: 'innerHTML', values: { name: name.trim() } });
  }
}
function renameProject(id, current) {
  const name = prompt('프로젝트 이름 변경:', current);
  if (name && name.trim() && name.trim() !== current) {
    htmx.ajax('PATCH', `/api/projects/${id}`, { target: '#project-mode', swap: 'innerHTML', values: { name: name.trim() } });
  }
}
function deleteProject(id, name) {
  if (confirm(`'${name}' 프로젝트를 삭제할까요? 소속 노트는 미분류로 이동합니다.`)) {
    htmx.ajax('DELETE', `/api/projects/${id}`, { target: '#project-mode', swap: 'innerHTML' });
  }
}
```

- [ ] **Step 5: dev 서버로 수동 검증**

```bash
# 기존 python 프로세스 전부 종료(워커 자식 포함) 후 단일 인스턴스 시작
# PowerShell: Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
python -m uvicorn main:app --reload --port 8000
```
브라우저 `http://localhost:8000`에서 확인:
1. 사이드바 `프로젝트별` 토글 → 빈 목록 + "+ 새 프로젝트" 표시
2. "+ 새 프로젝트"로 "회사 리서치" 생성 → 목록에 `회사 리서치 (0)` 등장, 공유 드롭다운에도 추가
3. 입력 패널 `현재 프로젝트: 회사 리서치` 선택 → 텍스트 탭으로 짧은 글 분석 → 노트가 프로젝트에 배정됨
4. `프로젝트별` → `회사 리서치 (1)` 클릭 → 해당 노트만 표시, "오늘의 추천 노트" 숨김, 라벨이 "회사 리서치"
5. 노트 카드의 프로젝트 셀렉트로 다른 노트를 `회사 리서치`로 재배정 → 카운트 증가
6. 프로젝트 ✎로 이름 변경 → 사이드바/드롭다운 반영, 해당 .md frontmatter `project:` 갱신
7. 프로젝트 ✕로 삭제 → 노트는 미분류로, frontmatter `project:` 비워짐
8. `주제별` 토글 → 기존 주제별 동작 정상(회귀 없음)
9. vault/{type}/*.md frontmatter에 `project:` 줄 존재 확인

- [ ] **Step 6: 전체 테스트 실행 + 커밋**

```bash
python -m pytest -v
git add templates/base.html templates/partials/note_card.html templates/partials/input_youtube.html templates/partials/input_pdf.html templates/partials/input_code.html templates/partials/input_text.html
git commit -m "feat: sidebar project mode toggle, shared project dropdown, card reassignment"
```

---

## 최종 검증 (전체 작업 후)

- [ ] `python -m pytest -v` 전체 통과
- [ ] 사이드바 주제별/프로젝트별 전환 정상
- [ ] 프로젝트 생성·이름변경·삭제 + 노트 배정·재배정 정상
- [ ] DB `project_id`와 .md frontmatter `project:` 일치
- [ ] 기존 기능(대기열, 요약, 태그검색, 다크모드) 회귀 없음
