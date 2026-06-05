import aiosqlite
import config

CREATE_ITEMS = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    summary TEXT,
    key_points TEXT,
    sections TEXT,
    tags TEXT,
    topic TEXT,
    summary_mode TEXT DEFAULT 'quick',
    main_arguments TEXT,
    insights TEXT,
    questions_raised TEXT,
    zettel_links TEXT,
    related_concepts TEXT,
    ai_provider TEXT,
    ai_models TEXT,
    api_cost_usd REAL DEFAULT 0.0,
    md_file_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

CREATE_API_COSTS = """
CREATE TABLE IF NOT EXISTS api_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    item_id INTEGER,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_ANALYSIS_TASKS = """
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,            -- queued | running | done | error
    source_type TEXT NOT NULL,
    title TEXT,
    progress TEXT DEFAULT '대기 중...',
    note_id INTEGER,
    error TEXT,
    attempts INTEGER DEFAULT 0,      -- 시도 횟수(첫 시도=1, 재시도=2)
    batch_index INTEGER DEFAULT 0,
    spec_json TEXT NOT NULL,         -- url/provider/mode/project_id 등 입력 복원용
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_PROJECT_DIGESTS = """
CREATE TABLE IF NOT EXISTS project_digests (
    project_id INTEGER PRIMARY KEY,
    digest_json TEXT NOT NULL,        -- {title, summary, insights, clusters[{theme,note_ids,description}]}
    note_count INTEGER DEFAULT 0,     -- 생성 시점 포함된 노트 수 (재생성 필요 여부 판단용)
    provider TEXT,                    -- claude-cli, codex-cli, claude, gpt
    model TEXT,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
)
"""


async def _ensure_column(db, column: str, decl: str) -> None:
    cursor = await db.execute("PRAGMA table_info(items)")
    cols = [r[1] for r in await cursor.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE items ADD COLUMN {column} {decl}")


async def init_db(db_path: str = config.DB_PATH) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_ITEMS)
        await db.execute(CREATE_SETTINGS)
        await db.execute(CREATE_API_COSTS)
        await db.execute(CREATE_PROJECTS)
        await db.execute(CREATE_ANALYSIS_TASKS)
        await db.execute(CREATE_PROJECT_DIGESTS)
        await _ensure_column(db, "project_id", "INTEGER")
        await _ensure_column(db, "timeline", "TEXT")
        await _ensure_column(db, "paragraphs", "TEXT")
        await _ensure_column(db, "transcript_segments", "TEXT")
        await db.commit()


def get_db(db_path: str = config.DB_PATH) -> aiosqlite.Connection:
    return aiosqlite.connect(db_path)
