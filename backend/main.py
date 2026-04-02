import os
import asyncio
import uuid
import re
import logging
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .core.config import settings
from .core.db import engine, Base, Task, User, SessionLocal
from .core.detector import run_forensic_pipeline
from .core import schemas

Path("backend/logs").mkdir(exist_ok=True)

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler = RotatingFileHandler(
    'backend/logs/app.log',
    maxBytes=10485760,
    backupCount=5
)
log_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        log_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.PROJECT_NAME)

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Maximum 10 uploads per minute."}
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=1440)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt


def authenticate_user(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    return resolve_user_from_token(token, db)


def resolve_user_from_token(token: str, db: Session) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = schemas.TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == token_data.username).first()
    if user is None:
        raise credentials_exception
    return user


UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 50 * 1024 * 1024

app.state.executor = ThreadPoolExecutor(max_workers=4)

model_verified = False
cleanup_task_running = False


async def run_forensic_task(task_id: str, file_path: str):
    db = SessionLocal()
    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            app.state.executor,
            run_forensic_pipeline,
            file_path,
            str(UPLOAD_DIR)
        )
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task and results:
            db_task.status = "complete"
            db_task.results = results
            db_task.progress = 100
            db_task.stage = "Analysis complete"
            db.commit()
            logger.info(f"Task {task_id} completed")
    except Exception as e:
        db.rollback()
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "error"
            db_task.stage = "Analysis failed"
            db.commit()
        logger.error(f"Task {task_id} failed: {str(e)}")
    finally:
        db.close()


def verify_model_on_startup():
    global model_verified
    model_path = "backend/ml/forgery_model.onnx"
    try:
        import onnxruntime as rt
        import numpy as np
        if not os.path.exists(model_path):
            logger.error(f"Model file not found at {model_path}. CNN scores will default to 0.5.")
            return False
        session = rt.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        dummy_input = np.random.randn(1, 3, 224, 224).astype(np.float32)
        _ = session.run(None, {input_name: dummy_input})
        model_verified = True
        logger.info("ONNX model loaded and verified.")
        return True
    except Exception as e:
        logger.error(f"Model verification failed: {e}. CNN scores will default to 0.5.")
        return False


def cleanup_old_uploads(max_age_hours: int = 48, upload_dir: Path = None):
    target_dir = upload_dir if upload_dir is not None else UPLOAD_DIR
    if not target_dir.exists():
        return
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    try:
        for file_path in target_dir.glob("*"):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    file_path.unlink()
    except Exception as e:
        logger.error(f"File cleanup error: {str(e)}")


@app.on_event("startup")
async def startup_event():
    verify_model_on_startup()

    async def periodic_cleanup():
        global cleanup_task_running
        cleanup_task_running = True
        while True:
            try:
                await asyncio.sleep(3600)
                cleanup_old_uploads(max_age_hours=48)
            except asyncio.CancelledError:
                cleanup_task_running = False
                break
            except Exception as e:
                logger.error(f"Cleanup run failed: {e}")

    app.state.cleanup_task = asyncio.create_task(periodic_cleanup())


@app.on_event("shutdown")
def shutdown_event():
    cleanup_task = getattr(app.state, "cleanup_task", None)
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
    app.state.executor.shutdown()
    cleanup_old_uploads()


@app.post("/api/auth/register", response_model=schemas.User)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/api/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/auth/token", response_model=schemas.Token)
def token(login_data: schemas.TokenRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, login_data.username, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/detect")
@limiter.limit("10/minute")
async def detect_image(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image (JPEG, PNG, WebP)")

        task_id = str(uuid.uuid4())
        raw_name = Path(file.filename or "upload.bin").name
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)
        file_path = UPLOAD_DIR / f"{task_id}_{safe_name}"
        
        sha256_hash = hashlib.sha256()
        bytes_written = 0
        
        with file_path.open("wb") as buffer:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE:
                    file_path.unlink()
                    raise HTTPException(status_code=413, detail="File exceeds maximum size of 50MB")
                sha256_hash.update(chunk)
                buffer.write(chunk)

        import cv2
        if cv2.imread(str(file_path)) is None:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")
        
        file_hash = sha256_hash.hexdigest()
        
        try:
            new_task = Task(
                task_id=task_id,
                user_id=current_user.id,
                status="processing",
                progress=5,
                stage="Processing upload...",
                sha256_hash=file_hash
            )
            db.add(new_task)
            db.commit()
            background_tasks.add_task(run_forensic_task, task_id, str(file_path))
            logger.info(f"Task {task_id} started for {file.filename} (Hash: {file_hash})")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create task: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to process request")
            
        return {
            "task_id": task_id,
            "status": "queued",
            "sha256_hash": file_hash,
            "message": "Analysis started. Poll /api/progress/{task_id} for updates."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in detect_image: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/progress/{task_id}")
async def get_progress(task_id: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == current_user.id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "task_id": task_id,
            "status": task.status,
            "progress": task.progress,
            "stage": task.stage
        }
    finally:
        db.close()


@app.get("/api/report/{task_id}")
async def get_report(task_id: str, current_user: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == current_user.id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Report not found")
        if task.status != "complete":
            raise HTTPException(status_code=202, detail=f"Analysis in progress. Status: {task.status}")
        return task.results
    finally:
        db.close()


@app.get("/api/uploads/{filename}")
async def get_upload(filename: str, token: Optional[str] = None, db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    current_user = resolve_user_from_token(token, db)
    safe_filename = os.path.basename(filename)
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not str(file_path).startswith(str(UPLOAD_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    candidate_task_id = safe_filename.split("_", 1)[0]
    try:
        uuid.UUID(candidate_task_id)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    owned_task = db.query(Task).filter(
        Task.task_id == candidate_task_id,
        Task.user_id == current_user.id
    ).first()

    if not owned_task:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        return FileResponse(file_path, media_type="image/png")
    except Exception as e:
        logger.error(f"Error serving file {filename}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving file")


@app.get("/api/health")
async def health():
    return {
        "status": "operational",
        "model_loaded": model_verified,
        "cleanup_active": cleanup_task_running
    }


@app.get("/")
async def root():
    return {"message": settings.PROJECT_NAME}


if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

    @app.exception_handler(404)
    async def spa_fallback(request, exc):
        if request.url.path.startswith("/api/"):
            detail = getattr(exc, "detail", "Not Found")
            return JSONResponse(status_code=404, content={"detail": detail})
        return FileResponse("frontend/dist/index.html")
