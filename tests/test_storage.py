import pytest
import json
import aiosqlite
from services.storage import save_note, get_note, record_api_cost, get_monthly_cost, list_notes
from services.ai.base import SummaryResult
from models import init_db

@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path

def make_result(mode="quick") -> SummaryResult:
    return SummaryResult(
        title="테스트 노트", language="ko", word_count=100,
        reading_time_min=1, sections=[],
        summary="요약입니다.", key_points=["핵심1"],
        tags=["AI"], suggested_topic="AI/ML",
        summary_mode=mode, cost_usd=0.003,
        models_used=["claude-sonnet-4-6"],
    )

@pytest.mark.asyncio
async def test_save_and_get_note(db, tmp_path):
    result = make_result()
    note_id = await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="https://youtube.com/watch?v=abc",
        result=result, ai_provider="claude",
    )
    assert note_id > 0

    note = await get_note(db, note_id)
    assert note["title"] == "테스트 노트"
    assert note["tags"] == ["AI"]

@pytest.mark.asyncio
async def test_save_note_creates_md_file(db, tmp_path):
    vault = tmp_path / "vault" / "youtube"
    vault.mkdir(parents=True)
    result = make_result()
    await save_note(
        db_path=db, vault_path=str(tmp_path / "vault"),
        source_type="youtube", source_url="https://youtube.com/watch?v=abc",
        result=result, ai_provider="claude",
    )
    md_files = list(vault.glob("*.md"))
    assert len(md_files) == 1

@pytest.mark.asyncio
async def test_record_and_get_monthly_cost(db):
    await record_api_cost(db, provider="claude", model="claude-sonnet-4-6",
                          input_tokens=1000, output_tokens=500, cost_usd=0.01)
    cost = await get_monthly_cost(db, provider="claude")
    assert cost == pytest.approx(0.01)

@pytest.mark.asyncio
async def test_save_note_with_project_id(db, tmp_path):
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
