import pytest
import json
import aiosqlite
from services.storage import save_note, get_note, record_api_cost, get_monthly_cost
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
    assert json.loads(note["tags"]) == ["AI"]

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
