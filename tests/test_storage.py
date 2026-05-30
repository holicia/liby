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
    assert note["timeline"] == []  # 항상 json.dumps([]) → []로 round-trip


@pytest.mark.asyncio
async def test_set_timeline_updates(db, tmp_path):
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    await set_timeline(db, nid, [{"t": 0, "label": "A"}])
    note = await get_note(db, nid)
    assert note["timeline"] == [{"t": 0, "label": "A"}]


def test_make_md_content_hierarchical():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": [
            {"heading": "1.1 B", "items": [
                {"text": "문단 본문 1", "quote": "원문 한 문장", "t": 90},
                {"text": "문단 본문 2"},
            ]}]}],
        summary="한 줄", key_points=[], tags=["x"], suggested_topic="AI",
        summary_mode="detailed", insights=["i"], questions_raised=["q"])
    md = _make_md_content("youtube", "u", r, "claude")
    assert "## 목차" in md
    assert "## 1. A" in md
    assert "### 1.1 B" in md
    assert "문단 본문 1" in md
    assert '> [1:30] "원문 한 문장"' in md
    assert "문단 본문 2" in md
    assert "## 인사이트" in md
    assert "## 탐구할 질문" in md
    assert "핵심 논거" not in md
    assert "\n\n\n" not in md


def test_make_md_content_quick_stays_flat():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="요약", key_points=["k1"], tags=[], suggested_topic="",
        summary_mode="quick")
    md = _make_md_content("text", "u", r, "claude")
    assert "## 핵심 포인트" in md
    assert "## 목차" not in md


def test_make_md_content_quick_paragraphs():
    from services.storage import _make_md_content
    from services.ai.base import SummaryResult
    r = SummaryResult(title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="요약", key_points=[], tags=[], suggested_topic="",
        summary_mode="quick",
        paragraphs=[
            {"text": "문단 A", "quote": "발췌", "t": 30},
            {"text": "문단 B"},
        ])
    md = _make_md_content("youtube", "u", r, "claude")
    assert "## 본문" in md
    assert "문단 A" in md
    assert '> [0:30] "발췌"' in md
    assert "문단 B" in md
    assert "## 핵심 포인트" not in md


@pytest.mark.asyncio
async def test_upgrade_to_detailed_persists_sections(db, tmp_path):
    from services.storage import upgrade_to_detailed
    nid = await save_note(db_path=db, vault_path=str(tmp_path / "vault"),
                          source_type="youtube", source_url="u",
                          result=make_result(), ai_provider="claude")
    detailed = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[{"heading": "1. A", "subsections": []}],
        summary="s", key_points=[], tags=[], suggested_topic="",
        summary_mode="detailed", insights=["i"], questions_raised=["q"], cost_usd=0.01)
    await upgrade_to_detailed(db, nid, detailed)
    note = await get_note(db, nid)
    assert note["summary_mode"] == "detailed"
    assert note["sections"] == [{"heading": "1. A", "subsections": []}]
    assert note["insights"] == ["i"]


@pytest.mark.asyncio
async def test_save_note_with_paragraphs(db, tmp_path):
    paragraphs = [
        {"text": "AI 해석 문단", "quote": "원문 한 문장", "t": 30},
        {"text": "두 번째 문단"},
    ]
    result = make_result()
    result.paragraphs = paragraphs
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=result, ai_provider="claude")
    note = await get_note(db, nid)
    assert note["paragraphs"] == paragraphs


@pytest.mark.asyncio
async def test_save_note_paragraphs_defaults_empty(db, tmp_path):
    result = make_result()
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="text",
                          source_url="u", result=result, ai_provider="claude")
    note = await get_note(db, nid)
    assert note["paragraphs"] == []


@pytest.mark.asyncio
async def test_upgrade_to_detailed_persists_paragraphs(db, tmp_path):
    from services.storage import upgrade_to_detailed
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="youtube",
                          source_url="u", result=make_result(), ai_provider="claude")
    detailed = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="s", key_points=[], tags=[], suggested_topic="",
        summary_mode="detailed", insights=["i"], questions_raised=["q"],
        paragraphs=[{"text": "문단", "quote": "인용"}], cost_usd=0.0)
    await upgrade_to_detailed(db, nid, detailed)
    note = await get_note(db, nid)
    assert note["paragraphs"] == [{"text": "문단", "quote": "인용"}]


@pytest.mark.asyncio
async def test_upgrade_to_detailed_preserves_existing_paragraphs(db, tmp_path):
    from services.storage import upgrade_to_detailed
    quick = make_result()
    quick.paragraphs = [{"text": "기존 문단", "quote": "기존 인용", "t": 5}]
    nid = await save_note(db_path=db, vault_path=str(tmp_path/"vault"), source_type="text",
                          source_url="u", result=quick, ai_provider="claude")
    detailed = SummaryResult(
        title="T", language="ko", word_count=0, reading_time_min=0,
        sections=[], summary="s", key_points=[], tags=[], suggested_topic="",
        summary_mode="detailed", insights=["i"], questions_raised=["q"], cost_usd=0.0)
    await upgrade_to_detailed(db, nid, detailed)
    note = await get_note(db, nid)
    assert note["paragraphs"] == [{"text": "기존 문단", "quote": "기존 인용", "t": 5}]
