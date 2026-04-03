from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import User
from backend.app.db.session import get_db

pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token_id() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_token_hash(value: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_token(value), expected_hash)


def _expiry(minutes: Optional[int] = None, days: Optional[int] = None) -> datetime:
    now = datetime.utcnow()
    if days is not None:
        return now + timedelta(days=days)
    return now + timedelta(minutes=minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_access_token(user: User, expires_minutes: Optional[int] = None) -> str:
    payload = {
        "sub": user.username,
        "uid": user.id,
        "jti": new_token_id(),
        "type": ACCESS_TOKEN_TYPE,
        "exp": _expiry(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    user: User,
    token_id: str,
    expires_days: Optional[int] = None,
) -> str:
    payload = {
        "sub": user.username,
        "uid": user.id,
        "jti": token_id,
        "type": REFRESH_TOKEN_TYPE,
        "exp": _expiry(days=expires_days or settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise credentials_exception from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise credentials_exception
    if not payload.get("sub"):
        raise credentials_exception
    return payload


def parse_refresh_token(token: str) -> Tuple[str, int, str]:
    payload = decode_token(token, REFRESH_TOKEN_TYPE)
    token_id = payload.get("jti")
    user_id = payload.get("uid")
    username = payload.get("sub")
    if not token_id or not user_id or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    return token_id, user_id_int, str(username)


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def get_user_from_token(token: str, db: Session) -> User:
    payload = decode_token(token, ACCESS_TOKEN_TYPE)
    username = payload["sub"]
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return get_user_from_token(token, db)
