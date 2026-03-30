import logging
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from PIL import Image
from slowapi import Limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.core.config import settings
from backend.core.detector import ForgeryDetector
from backend.core.ml_detector import MLDetector
from backend.core.progress import (
    TaskStatus,
    complete_task,
    create_task,
    error_task,
    get_progress,
    update_task_progress,
    get_report_data,
)
from backend.core.security import (
    TokenData,
    authenticate_user,
    create_access_token,
    decode_access_token,
)
from backend.core.telemetry import ANALYSIS_TASK_COUNT, metrics_endpoint, prometheus_middleware

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api")

app = FastAPI(title="Image Forgery Detection API", version="3.0.0")
app.middleware("http")(prometheus_middleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

LOCALHOST_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def _is_localhost_origin(origin: str) -> bool:
    return origin.startswith(("http://localhost", "https://localhost", "http://127.0.0.1", "https://127.0.0.1"))


origins_raw = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
allow_origin_regex = os.getenv("ALLOWED_ORIGIN_REGEX", "").strip() or None
debug_mode = os.getenv("DEBUG", "False").strip().lower() == "true"
if debug_mode and not allowed_origins:
    allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if not allow_origin_regex:
    has_localhost_origin = any(_is_localhost_origin(origin) for origin in allowed_origins)
    if debug_mode or not allowed_origins or has_localhost_origin:
        allow_origin_regex = LOCALHOST_ORIGIN_REGEX

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=bool(allowed_origins or allow_origin_regex),
    allow_methods=["*"],
    allow_headers=["*"],
)

detector = ForgeryDetector()
ml_detector = MLDetector()
UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def require_auth_if_enabled(request: Request) -> Optional[TokenData]:
    if not settings.API_KEY_REQUIRED:
        return None

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token.")
    return decode_access_token(token)


def validate_image_dimensions_bytes(file_bytes: bytes) -> None:
    try:
        from io import BytesIO
        with Image.open(BytesIO(file_bytes)):
            pass
    except Exception as exc:
        raise ValueError(f"Invalid image format: {exc}") from exc


@app.get("/api/metrics")
def get_metrics(_current_user: Optional[TokenData] = Depends(require_auth_if_enabled)):
    return metrics_endpoint()


@app.post("/api/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


def analyze_image_task(file_bytes: bytes, task_id: str):
    try:
        update_task_progress(task_id, TaskStatus.ML_SCORING, "Initializing ML scoring...", 10, 5.0)
        ml_res = ml_detector.predict_bytes(file_bytes)
        
        update_task_progress(task_id, TaskStatus.FORENSIC_SUITE, "Running EXIF, ELA, and copy-move analysis...", 40, 10.0)
        report = detector.detect_bytes(file_bytes, ml_result=ml_res)
        report["task_id"] = task_id
        
        complete_task(task_id, report)
    except Exception as exc:
        logger.error(f"Analysis failed: {exc}")
        error_task(task_id, str(exc))

@app.post("/api/detect")
@limiter.limit("30/minute")
async def handle_detection(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _current_user: Optional[TokenData] = Depends(require_auth_if_enabled),
):
    task_id = str(uuid.uuid4())

    create_task(task_id)
    ANALYSIS_TASK_COUNT.inc()

    try:
        file_bytes = await file.read()
        validate_image_dimensions_bytes(file_bytes)

        background_tasks.add_task(analyze_image_task, file_bytes, task_id)

        return JSONResponse(
            content={
                "report_id": task_id,
                "task_id": task_id,
                "status": "pending",
            }
        )
    except HTTPException as http_exc:
        error_task(task_id, str(http_exc.detail))
        raise
    except ValueError as value_error:
        logger.error("Validation error: %s", value_error)
        error_task(task_id, str(value_error))
        raise HTTPException(status_code=400, detail=str(value_error)) from value_error
    except Exception as exc:
        logger.exception("Queue error: %s", exc)
        error_task(task_id, str(exc))
        raise HTTPException(status_code=500, detail="Failed to queue analysis.") from exc


@app.get("/api/report/{report_id}")
async def get_report(
    report_id: str,
    _current_user: Optional[TokenData] = Depends(require_auth_if_enabled),
):
    report_data = get_report_data(report_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found.")

    return report_data


@app.get("/api/progress/{task_id}")
async def get_task_progress(
    task_id: str,
    _current_user: Optional[TokenData] = Depends(require_auth_if_enabled),
):
    progress = get_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Task not found or expired.")
    return progress


@app.get("/api/health")
async def health_check():
    health = {
        "status": "ok",
        "version": "3.0.0",
        "checks": {"auth_enabled": settings.API_KEY_REQUIRED},
    }
    return health


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("backend.main:app", host=host, port=port, reload=debug_mode)
