from backend.app.services.celery_app import celery_app
from backend.app.services.tasks import execute_task


@celery_app.task(name="backend.app.services.worker.run_forensic_job")
def run_forensic_job(task_id: str, file_path: str, upload_dir: str):
    execute_task(task_id, file_path, upload_dir)
    return {"task_id": task_id, "status": "complete"}
