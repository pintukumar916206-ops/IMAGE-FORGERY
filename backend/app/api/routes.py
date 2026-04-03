from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

import cv2
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Header, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    hash_token,
    new_csrf_token,
    new_token_id,
    parse_refresh_token,
    verify_token_hash,
)
from backend.app.db.models import RefreshToken, Task, User
from backend.app.db.session import get_db
from backend.app.services.tasks import enqueue_task, is_cleanup_running

router = APIRouter(prefix="/api")
limiter = Limiter(key_func=get_remote_address)

UsernameField = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@+-]+$"),
]
PasswordField = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    username: UsernameField
    password: PasswordField


class UserOut(BaseModel):
    id: int
    user_uuid: str
    username: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    csrf_token: str
    token_type: str = "bearer"


UPLOAD_DIR = Path(settings.UPLOAD_DIR)
MAX_FILE_SIZE = settings.MAX_FILE_SIZE_MB * 1024 * 1024


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/auth",
    )


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=settings.CSRF_COOKIE_SECURE,
        samesite=settings.CSRF_COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path="/api/auth",
    )


def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        httponly=False,
        secure=settings.CSRF_COOKIE_SECURE,
        samesite=settings.CSRF_COOKIE_SAMESITE,
        path="/",
    )


def _revoke_active_refresh_tokens(db: Session, user_id: int, compromised: bool = False) -> None:
    values = {"revoked_at": datetime.utcnow()}
    if compromised:
        values["is_compromised"] = True
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).update(
        values,
        synchronize_session=False,
    )


def _create_refresh_record(db: Session, user: User, request: Request) -> tuple[str, str]:
    token_id = new_token_id()
    refresh_token = create_refresh_token(user, token_id=token_id)
    csrf_token = new_csrf_token()
    record = RefreshToken(
        token_id=token_id,
        token_hash=hash_token(refresh_token),
        csrf_token_hash=hash_token(csrf_token),
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        issued_ip=request.client.host if request.client else None,
        issued_user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )
    db.add(record)
    return refresh_token, csrf_token


def _issue_token(payload: UserCreate, request: Request, response: Response, db: Session) -> TokenResponse:
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    refresh_token, csrf_token = _create_refresh_record(db, user, request)
    db.commit()
    _set_refresh_cookie(response, refresh_token)
    _set_csrf_cookie(response, csrf_token)
    return TokenResponse(access_token=create_access_token(user), csrf_token=csrf_token)


@router.post("/auth/register", response_model=UserOut)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    user = User(username=payload.username, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(request: Request, response: Response, payload: UserCreate, db: Session = Depends(get_db)):
    return _issue_token(payload, request, response, db)


@router.post("/auth/token", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def token(request: Request, response: Response, payload: UserCreate, db: Session = Depends(get_db)):
    return _issue_token(payload, request, response, db)


@router.post("/auth/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def refresh(
    request: Request,
    response: Response,
    csrf_token: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        token_id, user_id, username = parse_refresh_token(refresh_token)
    except HTTPException:
        _clear_refresh_cookie(response)
        _clear_csrf_cookie(response)
        raise
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_id == token_id, RefreshToken.user_id == user_id)
        .first()
    )

    if not record or not verify_token_hash(refresh_token, record.token_hash):
        _revoke_active_refresh_tokens(db, user_id=user_id, compromised=True)
        db.commit()
        _clear_refresh_cookie(response)
        _clear_csrf_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if not csrf_token or not csrf_cookie or csrf_token != csrf_cookie or not verify_token_hash(csrf_token, record.csrf_token_hash):
        _revoke_active_refresh_tokens(db, user_id=user_id, compromised=True)
        db.commit()
        _clear_refresh_cookie(response)
        _clear_csrf_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid CSRF token")

    if record.revoked_at is not None or record.expires_at <= datetime.utcnow() or record.is_compromised:
        if record.replaced_by_token_id:
            _revoke_active_refresh_tokens(db, user_id=user_id, compromised=True)
            db.commit()
        _clear_refresh_cookie(response)
        _clear_csrf_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked")

    user = db.query(User).filter(User.id == user_id, User.username == username).first()
    if not user:
        _clear_refresh_cookie(response)
        _clear_csrf_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    next_token_id = new_token_id()
    next_refresh_token = create_refresh_token(user, token_id=next_token_id)
    next_csrf_token = new_csrf_token()
    record.revoked_at = datetime.utcnow()
    record.replaced_by_token_id = next_token_id

    db.add(
        RefreshToken(
            token_id=next_token_id,
            token_hash=hash_token(next_refresh_token),
            csrf_token_hash=hash_token(next_csrf_token),
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            issued_ip=request.client.host if request.client else None,
            issued_user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
    )
    db.commit()

    _set_refresh_cookie(response, next_refresh_token)
    _set_csrf_cookie(response, next_csrf_token)
    return TokenResponse(access_token=create_access_token(user), csrf_token=next_csrf_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def logout(
    request: Request,
    response: Response,
    csrf_token: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if refresh_token:
        try:
            token_id, user_id, _ = parse_refresh_token(refresh_token)
        except HTTPException:
            token_id = None
            user_id = None
        if token_id and user_id:
            record = (
                db.query(RefreshToken)
                .filter(RefreshToken.token_id == token_id, RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .first()
            )
            if not record or not csrf_token or not verify_token_hash(csrf_token, record.csrf_token_hash):
                _clear_refresh_cookie(response)
                _clear_csrf_cookie(response)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid CSRF token")
            if not csrf_cookie or csrf_cookie != csrf_token:
                _clear_refresh_cookie(response)
                _clear_csrf_cookie(response)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid CSRF token")
            record.revoked_at = datetime.utcnow()
            db.commit()
    _clear_refresh_cookie(response)
    _clear_csrf_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@router.post("/detect")
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def detect_image(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    task_id = str(uuid.uuid4())
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "upload.bin").name)
    file_path = UPLOAD_DIR / f"{task_id}_{safe_name}"

    digest = hashlib.sha256()
    bytes_written = 0
    with file_path.open("wb") as stream:
        while True:
            chunk = await file.read(8192)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_FILE_SIZE:
                file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB")
            digest.update(chunk)
            stream.write(chunk)

    if cv2.imread(str(file_path)) is None:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")

    task = Task(
        task_id=task_id,
        user_id=current_user.id,
        status="processing",
        progress=5,
        stage="Queued for analysis",
        sha256_hash=digest.hexdigest(),
        source_filename=safe_name,
    )
    db.add(task)
    db.commit()

    queue_mode = enqueue_task(background_tasks, task_id, str(file_path), str(UPLOAD_DIR))
    return {
        "task_id": task_id,
        "status": "queued",
        "queue_mode": queue_mode,
        "message": "Analysis started. Poll /api/progress/{task_id}.",
    }


@router.get("/progress/{task_id}")
@limiter.limit(settings.RATE_LIMIT_STATUS)
def get_progress(request: Request, task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task.task_id, "status": task.status, "progress": task.progress, "stage": task.stage}


@router.get("/report/{task_id}")
@limiter.limit(settings.RATE_LIMIT_STATUS)
def get_report(request: Request, task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Report not found")
    if task.status != "complete":
        raise HTTPException(status_code=202, detail=f"Analysis in progress. Status: {task.status}")
    return task.results


@router.get("/uploads/{filename}")
@limiter.limit(settings.RATE_LIMIT_STATUS)
def get_upload(request: Request, filename: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    safe_filename = os.path.basename(filename)
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    task_id_candidate = safe_filename.split("_", 1)[0]
    try:
        uuid.UUID(task_id_candidate)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    owned_task = db.query(Task).filter(Task.task_id == task_id_candidate, Task.user_id == current_user.id).first()
    if not owned_task:
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(file_path)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "operational", "method": "forensic", "cleanup_active": is_cleanup_running()}
