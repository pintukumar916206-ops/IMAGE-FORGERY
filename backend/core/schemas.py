from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from datetime import datetime


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    user_uuid: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenData(BaseModel):
    username: Optional[str] = None


class TaskBase(BaseModel):
    task_id: str
    status: str
    progress: int
    stage: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class Task(TaskBase):
    sha256_hash: Optional[str] = None
    results: Optional[Any] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
