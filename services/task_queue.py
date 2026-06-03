"""분석 작업 큐 + 영구화 + 자동 재시도 1회.

- 라우터는 spec(dict)만 전달하면 worker가 등록된 builder로 do_work를 재구성
- spec은 SQLite analysis_tasks에 저장되어 서버 재시작 시 replay 가능
- 실패 시 task.attempts <= MAX_ATTEMPTS면 자동으로 다시 큐에 넣음
- builder 미등록 source_type(pdf/text/code/markdown 등)은 기존처럼 in-memory 흐름 유지
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import aiosqlite
import config

DoWork = Callable[["AnalysisTask"], Awaitable[None]]
Builder = Callable[[dict], DoWork]

MAX_ATTEMPTS = 2  # 첫 시도 + 1회 재시도


@dataclass
class AnalysisTask:
    id: str
    status: str       # queued | running | done | error
    source_type: str = ""
    title: str = ""
    progress: str = "대기 중..."
    batch_index: int = 0
    note_id: int | None = None
    error: str | None = None
    attempts: int = 0
    spec: dict = field(default_factory=dict)


_tasks: dict[str, AnalysisTask] = {}
_queue: asyncio.Queue = asyncio.Queue()
_is_running = False
_batch_total = 0
_BUILDERS: dict[str, Builder] = {}


def register_builder(source_type: str, builder: Builder) -> None:
    """source_type → do_work 재구성 함수 등록. 영구화/재시도 대상이 된다."""
    _BUILDERS[source_type] = builder


async def _save_task(task: AnalysisTask, db_path: str | None = None) -> None:
    """UPSERT. spec_json 포함. builder가 등록된 source_type만 호출됨."""
    path = db_path or config.DB_PATH
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """INSERT INTO analysis_tasks
                 (id, status, source_type, title, progress, note_id, error,
                  attempts, batch_index, spec_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, title=excluded.title, progress=excluded.progress,
                 note_id=excluded.note_id, error=excluded.error, attempts=excluded.attempts,
                 batch_index=excluded.batch_index, updated_at=CURRENT_TIMESTAMP""",
            (task.id, task.status, task.source_type, task.title, task.progress,
             task.note_id, task.error, task.attempts, task.batch_index,
             json.dumps(task.spec, ensure_ascii=False)),
        )
        await db.commit()


def new_task(source_type: str = "", title: str = "", spec: dict | None = None) -> AnalysisTask:
    global _batch_total
    if not any(t.status in ("queued", "running") for t in _tasks.values()):
        _batch_total = 0
    _batch_total += 1
    task_id = uuid.uuid4().hex[:8]
    task = AnalysisTask(
        id=task_id, status="queued", source_type=source_type,
        title=title, batch_index=_batch_total, spec=spec or {},
    )
    _tasks[task_id] = task
    if source_type in _BUILDERS:
        # fire-and-forget: 영구화 실패는 메모리 동작을 막지 않음
        asyncio.create_task(_save_task(task))
    return task


def queue_meta(task: AnalysisTask) -> dict:
    return {"batch_total": _batch_total, "batch_index": task.batch_index}


def get_task(task_id: str) -> AnalysisTask | None:
    return _tasks.get(task_id)


async def enqueue(task: AnalysisTask, coro_fn: DoWork | None = None) -> None:
    """coro_fn None이면 worker가 builder로 재구성(영구화·재시도 가능).
    coro_fn 직접 전달은 in-memory 라우터(pdf/text/...)용 호환 경로."""
    await _queue.put((task, coro_fn))


async def run_worker() -> None:
    global _is_running
    log = logging.getLogger(__name__)
    while True:
        task, coro_fn = await _queue.get()
        _is_running = True
        task.status = "running"
        task.attempts += 1
        task.progress = (
            f"재시도 중... ({task.attempts}/{MAX_ATTEMPTS})"
            if task.attempts > 1 else "AI 분석 시작..."
        )
        # 이전 에러는 새 시도에서 지움
        task.error = None
        persisted = task.source_type in _BUILDERS
        if persisted:
            await _save_task(task)
        try:
            if coro_fn is None:
                builder = _BUILDERS.get(task.source_type)
                if builder is None:
                    raise RuntimeError(
                        f"source_type={task.source_type!r}용 builder 미등록"
                    )
                coro_fn = builder(task.spec)
            await coro_fn(task)
            task.status = "done"
        except Exception as e:
            log.error(
                "task %s failed (attempt %d/%d, %s): %s",
                task.id, task.attempts, MAX_ATTEMPTS, type(e).__name__, e,
                exc_info=True,
            )
            task.error = str(e)
            if task.attempts < MAX_ATTEMPTS and persisted:
                # 자동 재시도 — 다시 큐에 넣음. attempts는 보존(다음 진입 시 +1).
                task.status = "queued"
                task.progress = "재시도 대기 중..."
                # 인메모리 큐 재투입; coro_fn=None으로 builder 재구성
                if persisted:
                    await _save_task(task)
                await _queue.put((task, None))
            else:
                task.status = "error"
        finally:
            _is_running = False
            _queue.task_done()
            if persisted and task.status in ("done", "error"):
                await _save_task(task)


async def restore_pending_tasks(db_path: str | None = None) -> int:
    """서버 시작 시 queued/running 상태로 남은 task들을 다시 큐에 넣는다.
    'running' → 'queued'로 reset(이전 process가 끊긴 시점부터 다시 시도).
    attempts는 보존하되 MAX_ATTEMPTS 이미 도달한 task는 'error'로 마무리.
    반환: 복원한 task 수.
    """
    path = db_path or config.DB_PATH
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM analysis_tasks WHERE status IN ('queued', 'running')"
        )
        rows = await cur.fetchall()
    restored = 0
    for r in rows:
        if r["source_type"] not in _BUILDERS:
            continue
        try:
            spec = json.loads(r["spec_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        attempts = r["attempts"] or 0
        if attempts >= MAX_ATTEMPTS:
            # 이미 다 써버린 task — 더 재시도 안 함. error 종결.
            async with aiosqlite.connect(path) as db:
                await db.execute(
                    "UPDATE analysis_tasks SET status='error', "
                    "error=COALESCE(error,'서버 재시작 시 시도 횟수 초과'),"
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (r["id"],),
                )
                await db.commit()
            continue
        task = AnalysisTask(
            id=r["id"], status="queued", source_type=r["source_type"],
            title=r["title"] or "", progress="대기 중... (복원됨)",
            batch_index=r["batch_index"] or 0, note_id=r["note_id"],
            error=r["error"], attempts=attempts, spec=spec,
        )
        _tasks[task.id] = task
        await _queue.put((task, None))
        restored += 1
    # running으로 남은 row를 queued로 reset
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE analysis_tasks SET status='queued', "
            "updated_at=CURRENT_TIMESTAMP WHERE status='running'"
        )
        await db.commit()
    return restored


def _reset_for_tests() -> None:
    """테스트 격리용: 모듈 전역 상태 초기화."""
    global _tasks, _queue, _is_running, _batch_total
    _tasks = {}
    _queue = asyncio.Queue()
    _is_running = False
    _batch_total = 0
    _BUILDERS.clear()
