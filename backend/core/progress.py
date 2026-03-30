from enum import Enum
from typing import Dict, Optional
import time

class TaskStatus(str, Enum):
    PENDING = "pending"
    EXIF_ANALYSIS = "exif_analysis"
    ELA_ANALYSIS = "ela_analysis"
    SIFT_ANALYSIS = "sift_analysis"
    ML_SCORING = "ml_scoring"
    FORENSIC_SUITE = "forensic_suite"
    COMPLETE = "complete"
    ERROR = "error"

_tasks = {}
_reports = {}

def create_task(task_id: str) -> None:
    _tasks[task_id] = {
        "task_id": task_id,
        "status": TaskStatus.PENDING.value,
        "progress": 0,
        "stage": "Initializing...",
        "eta_seconds": 10.0,
        "timestamp": time.time()
    }

def update_task_progress(task_id: str, status: TaskStatus, stage: str, progress: int, eta: float) -> None:
    if task_id in _tasks:
        _tasks[task_id].update({
            "status": status.value if isinstance(status, TaskStatus) else status,
            "progress": progress,
            "stage": stage,
            "eta_seconds": eta,
            "timestamp": time.time()
        })

def get_progress(task_id: str) -> Optional[Dict]:
    return _tasks.get(task_id)

def complete_task(task_id: str, final_report: dict = None) -> None:
    if task_id in _tasks:
        _tasks[task_id].update({
            "status": TaskStatus.COMPLETE.value,
            "progress": 100,
            "stage": "Complete",
            "eta_seconds": 0.0,
            "timestamp": time.time(),
            "report_id": task_id
        })
    if final_report:
        _reports[task_id] = final_report

def error_task(task_id: str, error_message: str) -> None:
    if task_id in _tasks:
        _tasks[task_id].update({
            "status": TaskStatus.ERROR.value,
            "progress": 0,
            "stage": f"Error: {error_message}",
            "eta_seconds": 0.0,
            "timestamp": time.time(),
            "error": error_message
        })

def get_report_data(report_id: str) -> Optional[Dict]:
    return _reports.get(report_id)
