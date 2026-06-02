import asyncio
import uuid
from dataclasses import dataclass

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

_tasks: dict[str, AnalysisTask] = {}
_queue: asyncio.Queue = asyncio.Queue()
_is_running = False
_batch_total = 0   # 현재 배치에 제출된 총 작업 수 (완료돼도 줄지 않음)

def new_task(source_type: str = "", title: str = "") -> AnalysisTask:
    global _batch_total
    # 진행 중인 작업이 하나도 없으면 새 배치 시작
    if not any(t.status in ("queued", "running") for t in _tasks.values()):
        _batch_total = 0
    _batch_total += 1
    task_id = uuid.uuid4().hex[:8]
    task = AnalysisTask(
        id=task_id, status="queued", source_type=source_type,
        title=title, batch_index=_batch_total,
    )
    _tasks[task_id] = task
    return task

def queue_meta(task: AnalysisTask) -> dict:
    """대기열 표시용 메타: 배치 총 개수(고정)와 이 작업의 배치 내 순번(고정)."""
    return {"batch_total": _batch_total, "batch_index": task.batch_index}

def get_task(task_id: str) -> AnalysisTask | None:
    return _tasks.get(task_id)

async def enqueue(task: AnalysisTask, coro_fn) -> None:
    await _queue.put((task, coro_fn))

async def run_worker() -> None:
    global _is_running
    while True:
        task, coro_fn = await _queue.get()
        _is_running = True
        task.status = "running"
        try:
            await coro_fn(task)
            task.status = "done"
        except Exception as e:
            import logging, traceback
            logging.getLogger(__name__).error(
                f"task {task.id} failed ({type(e).__name__}): {e}\n{traceback.format_exc()}"
            )
            task.status = "error"
            task.error = str(e)
        finally:
            _is_running = False
            _queue.task_done()
