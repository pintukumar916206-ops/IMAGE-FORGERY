from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from .config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

class TokenData(BaseModel):
    username: str
    role: str

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=role)
    except jwt.PyJWTError:
        raise credentials_exception
    if token_data.role not in ["admin", "analyst"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return token_data

def verify_token(token: str = Depends(oauth2_scheme)):
    return decode_access_token(token)

def authenticate_user(username: str, password: str) -> Optional[TokenData]:
    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        return TokenData(username=username, role="admin")
    if username == settings.ANALYST_USERNAME and password == settings.ANALYST_PASSWORD:
        return TokenData(username=username, role="analyst")
    return None
