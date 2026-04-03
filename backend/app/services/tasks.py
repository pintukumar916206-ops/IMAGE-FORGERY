from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Task
from backend.app.db.session import SessionLocal
from backend.app.services.detector import run_forensic_analysis

logger = logging.getLogger(__name__)

_cleanup_task: Optional[asyncio.Task] = None
_cleanup_running: bool = False
_executor = None


def _create_executor():
    use_process_pool = settings.USE_PROCESS_POOL and not os.getenv("PYTEST_CURRENT_TEST")
    if use_process_pool:
        workers = max(1, (os.cpu_count() or 2) - 1)
        return ProcessPoolExecutor(max_workers=workers)
    return ThreadPoolExecutor(max_workers=4)


def get_executor():
    global _executor
    if _executor is None:
        _executor = _create_executor()
    return _executor


def shutdown_executor():
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def cleanup_old_uploads(upload_dir: Path, max_age_hours: int):
    if not upload_dir.exists():
        return

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    for file_path in upload_dir.glob("*"):
        if not file_path.is_file():
            continue
        age = now - file_path.stat().st_mtime
        if age > max_age_seconds:
            try:
                file_path.unlink()
            except OSError:
                logger.warning("Failed to remove stale upload: %s", file_path)


def is_cleanup_running() -> bool:
    return _cleanup_running


async def _cleanup_loop(upload_dir: Path):
    global _cleanup_running
    _cleanup_running = True
    try:
        while True:
            await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
            cleanup_old_uploads(upload_dir, settings.CLEANUP_MAX_AGE_HOURS)
    except asyncio.CancelledError:
        pass
    finally:
        _cleanup_running = False


def start_cleanup_worker(upload_dir: Path):
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    _cleanup_task = asyncio.create_task(_cleanup_loop(upload_dir))


async def stop_cleanup_worker(upload_dir: Path):
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await _cleanup_task
    cleanup_old_uploads(upload_dir, settings.CLEANUP_MAX_AGE_HOURS)


def execute_task(task_id: str, file_path: str, upload_dir: str):
    db: Session = SessionLocal()
    try:
        result = run_forensic_analysis(file_path, upload_dir)
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if task:
            task.status = "complete"
            task.progress = 100
            task.stage = "Analysis complete"
            task.results = result
            db.commit()
    except Exception as exc:
        db.rollback()
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if task:
            task.status = "error"
            task.stage = "Analysis failed"
            task.results = {"error": str(exc), "method": "forensic"}
            db.commit()
        logger.error("Task %s failed: %s", task_id, exc, exc_info=True)
    finally:
        db.close()


async def run_task(task_id: str, file_path: str, upload_dir: str):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(get_executor(), execute_task, task_id, file_path, upload_dir)


def enqueue_task(background_tasks, task_id: str, file_path: str, upload_dir: str):
    if settings.CELERY_ENABLED:
        from backend.app.services.worker import run_forensic_job

        run_forensic_job.delay(task_id, file_path, upload_dir)
        return "celery"

    background_tasks.add_task(run_task, task_id, file_path, upload_dir)
    return "local"
