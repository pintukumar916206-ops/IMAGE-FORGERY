import logging
import os
import uuid
import asyncio
import time
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi import Limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.core.config import settings
from backend.core.progress import (
    TaskStatus,
    complete_task,
    create_task,
    error_task,
    get_progress,
    update_task_progress,
    get_report_data,
)
from backend.core.telemetry import ANALYSIS_TASK_COUNT, metrics_endpoint, prometheus_middleware

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api")

app = FastAPI(title="Forensic Image Suite API", version="4.0.0")
app.middleware("http")(prometheus_middleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(exist_ok=True)

# ProcessPool for CPU-bound forensic analysis
analysis_executor = ProcessPoolExecutor(max_workers=max(1, cpu_count() - 1))

def analyze_image_worker(file_path: str, task_id: str):
    """
    Sub-process worker for forensic analysis to bypass GIL.
    """
    from backend.core.detector import ForgeryDetector
    from backend.core.ml_detector import MLDetector
    from backend.core.progress import update_task_progress, complete_task, error_task, TaskStatus
    import os

    detector = ForgeryDetector()
    ml_detector = MLDetector()

    try:
        update_task_progress(task_id, TaskStatus.ML_SCORING, "Running probabilistic validation...", 20, 2.0)
        ml_res = ml_detector.predict_file(file_path)
        
        update_task_progress(task_id, TaskStatus.FORENSIC_SUITE, "Executing ELA and SIFT analysis...", 50, 5.0)
        report = detector.detect_file(file_path, ml_result=ml_res)
        report["task_id"] = task_id
        
        complete_task(task_id, report)
    except Exception as exc:
        error_task(task_id, str(exc))
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

def executor_wrapper(file_path: str, task_id: str):
    """
    Synchronous wrapper for thread-pooling background tasks.
    """
    try:
        future = analysis_executor.submit(analyze_image_worker, file_path, task_id)
        future.result() # Wait for completion in the background thread
    except Exception as e:
        logger.error(f"Background execution failed: {e}")

async def _garbage_collector():
    while True:
        try:
            from backend.core import db
            exp_hours = settings.REPORT_EXPIRATION_HOURS
            now = time.time()
            for filename in os.listdir(UPLOAD_DIR):
                filepath = UPLOAD_DIR / filename
                if filepath.is_file() and (now - os.path.getmtime(filepath) > exp_hours * 3600):
                    os.remove(filepath)
            db.cleanup_old_records(exp_hours)
        except Exception as e:
            logger.error(f"GC cycle failed: {e}")
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_garbage_collector())

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}

@app.get("/api/metrics")
async def get_metrics():
    return metrics_endpoint()

@app.post("/api/detect")
@limiter.limit("15/minute")
async def handle_detection(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())
    create_task(task_id)
    ANALYSIS_TASK_COUNT.inc()
    
    file_path = str(UPLOAD_DIR / f"{task_id}.jpg")
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Offload to ProcessPool via Starlette background thread
        background_tasks.add_task(executor_wrapper, file_path, task_id)
        
        return JSONResponse(content={"task_id": task_id, "status": "processing"})
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        error_task(task_id, str(e))
        raise HTTPException(status_code=500, detail="Failed to initiate analysis pipeline.")

@app.get("/api/progress/{task_id}")
async def get_task_progress(task_id: str):
    progress = get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Task not found")
    return progress

@app.get("/api/report/{task_id}")
async def get_report(task_id: str):
    report = get_report_data(task_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not available")
    return report

@app.get("/api/media/{filename}")
async def get_media(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid resource path")
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resource not found")
    return FileResponse(file_path)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
