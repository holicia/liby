import pytest
import json
import aiosqlite
from services.storage import save_note, get_note, record_api_cost, get_monthly_cost, list_notes, set_timeline
from services.storage import (
    create_project, list_projects, rename_project, delete_project,
    unassigned_count, set_note_project,
)
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
    assert "project: Old" not in content


@pytest.mark.asyncio
async def test_set_note_project_none_removes_frontmatter(db, tmp_path):
    pid = await create_project(db, "P1")
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", project_id=pid)
    path = (await get_note(db, nid))["md_file_path"]
    assert "project: P1" in open(path, encoding="utf-8").read()
    await set_note_project(db, nid, None)
    assert (await get_note(db, nid))["project_id"] is None
    assert "project:" not in open(path, encoding="utf-8").read()


@pytest.mark.asyncio
async def test_create_project_empty_name_raises(db):
    with pytest.raises(ValueError):
        await create_project(db, "   ")


@pytest.mark.asyncio
async def test_delete_project_unassigns_notes(db, tmp_path):
    pid = await create_project(db, "P1")
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", project_id=pid)
    await delete_project(db, pid)
    assert (await get_note(db, nid))["project_id"] is None
    assert all(p["id"] != pid for p in await list_projects(db))
    content = open((await get_note(db, nid))["md_file_path"], encoding="utf-8").read()
    assert "project:" not in content   # 미분류가 되면 project: 줄이 제거됨


@pytest.mark.asyncio
async def test_save_note_with_timeline(db, tmp_path):
    chapters = [{"t": 0, "label": "인트로"}, {"t": 90, "label": "본론"}]
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude", timeline=chapters)
    note = await get_note(db, nid)
    assert note["timeline"] == chapters

@pytest.mark.asyncio
async def test_save_note_timeline_defaults_empty(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="pdf",
                          source_url="u", result=make_result(), ai_provider="claude")
    note = await get_note(db, nid)
    assert note["timeline"] in (None, [], "")

@pytest.mark.asyncio
async def test_set_timeline_updates(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    await set_timeline(db, nid, [{"t": 0, "label": "A"}])
    note = await get_note(db, nid)
    assert note["timeline"] == [{"t": 0, "label": "A"}]
