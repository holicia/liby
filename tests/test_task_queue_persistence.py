"""task_queue의 SQLite 영구화 + 자동 재시도 1회 검증."""
import asyncio
import json

import pytest
import aiosqlite

from models import init_db
from services import task_queue as tq


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch, tmp_path):
    """매 테스트 격리: 임시 DB + 모듈 전역 reset."""
    db_path = str(tmp_path / "tq.db")
    await init_db(db_path)
    monkeypatch.setattr("config.DB_PATH", db_path)
    tq._reset_for_tests()
    yield db_path
    tq._reset_for_tests()


async def _row(db_path: str, task_id: str) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM analysis_tasks WHERE id=?", (task_id,))
        r = await cur.fetchone()
        return dict(r) if r else None


@pytest.mark.asyncio
async def test_new_task_persists_when_builder_registered(_isolated):
    """source_type에 builder가 등록되어 있으면 DB에 row 생성."""
    tq.register_builder("youtube", lambda spec: None)
    spec = {"url": "https://youtu.be/abc", "provider": "claude-cli", "mode": "quick"}
    task = tq.new_task("youtube", "샘플 제목", spec=spec)
    # fire-and-forget save_task 완료 대기
    await asyncio.sleep(0.05)
    row = await _row(_isolated, task.id)
    assert row is not None
    assert row["status"] == "queued"
    assert row["source_type"] == "youtube"
    assert row["title"] == "샘플 제목"
    assert json.loads(row["spec_json"]) == spec


@pytest.mark.asyncio
async def test_new_task_does_not_persist_without_builder(_isolated):
    """builder 미등록 source_type(pdf 등)은 in-memory only."""
    spec = {"file": "/tmp/x.pdf"}
    task = tq.new_task("pdf", "pdf 제목", spec=spec)
    await asyncio.sleep(0.05)
    assert await _row(_isolated, task.id) is None


@pytest.mark.asyncio
async def test_worker_retries_once_on_failure(_isolated):
    """첫 시도 실패 → 자동 재시도 1회 (총 2회 시도). 두 번째 성공 시 done."""
    call_count = {"n": 0}

    def builder(spec):
        async def do_work(t):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first attempt boom")
            t.note_id = 42
        return do_work

    tq.register_builder("youtube", builder)
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    worker = asyncio.create_task(tq.run_worker())
    await tq.enqueue(task)
    # 두 번 처리 끝나길 대기
    for _ in range(50):
        await asyncio.sleep(0.05)
        if task.status in ("done", "error"):
            break
    worker.cancel()
    assert call_count["n"] == 2
    assert task.status == "done"
    assert task.attempts == 2
    assert task.note_id == 42


@pytest.mark.asyncio
async def test_worker_marks_error_after_max_attempts(_isolated):
    """두 시도 모두 실패하면 status='error'로 종결, 추가 재시도 없음."""
    call_count = {"n": 0}

    def builder(spec):
        async def do_work(t):
            call_count["n"] += 1
            raise RuntimeError("persistent boom")
        return do_work

    tq.register_builder("youtube", builder)
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    worker = asyncio.create_task(tq.run_worker())
    await tq.enqueue(task)
    for _ in range(50):
        await asyncio.sleep(0.05)
        if task.status == "error":
            break
    worker.cancel()
    assert call_count["n"] == tq.MAX_ATTEMPTS  # 2회로 끝
    assert task.status == "error"
    assert "persistent boom" in (task.error or "")
    row = await _row(_isolated, task.id)
    assert row["status"] == "error"
    assert row["attempts"] == tq.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_restore_pending_resets_running_to_queued(_isolated):
    """startup replay: 이전 process에서 running으로 끊긴 task를 queued로 reset + 재큐."""
    # DB에 running 상태 task 가짜로 삽입
    spec = {"url": "https://youtu.be/x", "provider": "claude-cli", "mode": "quick"}
    async with aiosqlite.connect(_isolated) as db:
        await db.execute(
            """INSERT INTO analysis_tasks
                 (id, status, source_type, title, attempts, batch_index, spec_json)
               VALUES ('orphan1', 'running', 'youtube', 'orphan title', 1, 1, ?)""",
            (json.dumps(spec),),
        )
        await db.commit()
    # builder 등록 후 restore
    tq.register_builder("youtube", lambda s: (lambda t: None))
    restored = await tq.restore_pending_tasks(_isolated)
    assert restored == 1
    assert "orphan1" in tq._tasks
    row = await _row(_isolated, "orphan1")
    assert row["status"] == "queued"
    # 재큐된 task가 attempts 보존
    assert tq._tasks["orphan1"].attempts == 1


@pytest.mark.asyncio
async def test_restore_pending_marks_error_if_max_attempts_reached(_isolated):
    """이전 run에서 MAX_ATTEMPTS 다 소진된 task는 restore 시 error로 마무리(재시도 없음)."""
    spec = {"url": "u"}
    async with aiosqlite.connect(_isolated) as db:
        await db.execute(
            """INSERT INTO analysis_tasks
                 (id, status, source_type, title, attempts, batch_index, spec_json)
               VALUES ('exhausted', 'running', 'youtube', 't', ?, 1, ?)""",
            (tq.MAX_ATTEMPTS, json.dumps(spec)),
        )
        await db.commit()
    tq.register_builder("youtube", lambda s: (lambda t: None))
    restored = await tq.restore_pending_tasks(_isolated)
    assert restored == 0
    row = await _row(_isolated, "exhausted")
    assert row["status"] == "error"


@pytest.mark.asyncio
async def test_cancel_queued_task_marks_cancelled(_isolated):
    """queued 상태 task를 cancel하면 status='cancelled', error=사용자 취소 메시지."""
    tq.register_builder("youtube", lambda s: (lambda t: None))
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    await asyncio.sleep(0.05)
    ok = await tq.cancel_task(task.id)
    assert ok is True
    assert task.status == "cancelled"
    assert task.progress == "취소됨"
    assert "사용자" in (task.error or "")
    row = await _row(_isolated, task.id)
    assert row["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_running_task_raises_cancelled_error(_isolated):
    """running 상태 task를 cancel하면 worker 안 coro_fn에 CancelledError 전달."""
    started = asyncio.Event()
    cancelled_seen = asyncio.Event()

    def builder(spec):
        async def do_work(t):
            started.set()
            try:
                await asyncio.sleep(10)  # 충분히 길게
            except asyncio.CancelledError:
                cancelled_seen.set()
                raise
        return do_work

    tq.register_builder("youtube", builder)
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    worker = asyncio.create_task(tq.run_worker())
    await tq.enqueue(task)
    await asyncio.wait_for(started.wait(), timeout=2.0)
    # 이제 running 상태에서 cancel
    ok = await tq.cancel_task(task.id)
    assert ok is True
    await asyncio.wait_for(cancelled_seen.wait(), timeout=2.0)
    # worker가 cancelled로 종결할 때까지 잠깐 대기
    for _ in range(30):
        await asyncio.sleep(0.05)
        if task.status == "cancelled":
            break
    worker.cancel()
    assert task.status == "cancelled"
    # 자동 재시도 없음
    assert task.attempts == 1


@pytest.mark.asyncio
async def test_cancel_already_done_returns_false(_isolated):
    """이미 종결된 task에 cancel 호출 → noop, False 반환."""
    tq.register_builder("youtube", lambda s: (lambda t: None))
    task = tq.new_task("youtube", "t", spec={"url": "u"})
    await asyncio.sleep(0.05)
    task.status = "done"
    ok = await tq.cancel_task(task.id)
    assert ok is False


@pytest.mark.asyncio
async def test_cancel_unknown_id_returns_false(_isolated):
    """존재하지 않는 task id에 cancel → False."""
    ok = await tq.cancel_task("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_restore_skips_unknown_source_type(_isolated):
    """builder 없는 source_type은 restore에서 skip(메모리에도 안 들어감)."""
    async with aiosqlite.connect(_isolated) as db:
        await db.execute(
            """INSERT INTO analysis_tasks
                 (id, status, source_type, title, attempts, batch_index, spec_json)
               VALUES ('alien', 'queued', 'unknown-source', 't', 0, 1, '{}')""",
        )
        await db.commit()
    restored = await tq.restore_pending_tasks(_isolated)
    assert restored == 0
    assert "alien" not in tq._tasks
