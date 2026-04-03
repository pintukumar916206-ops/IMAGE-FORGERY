from __future__ import annotations

import os
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def split_origins(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Image Forensic Analysis System")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./forgery.sqlite")
    ALLOWED_ORIGINS: List[str] = Field(
        default_factory=lambda: split_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        )
    )
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    RATE_LIMIT_AUTH: str = os.getenv("RATE_LIMIT_AUTH", "20/minute")
    RATE_LIMIT_UPLOAD: str = os.getenv("RATE_LIMIT_UPLOAD", "10/minute")
    RATE_LIMIT_STATUS: str = os.getenv("RATE_LIMIT_STATUS", "120/minute")
    CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))
    CLEANUP_MAX_AGE_HOURS: int = int(os.getenv("CLEANUP_MAX_AGE_HOURS", "48"))
    PRODUCTION: bool = os.getenv("PRODUCTION", "false").lower() == "true"
    USE_PROCESS_POOL: bool = os.getenv("USE_PROCESS_POOL", "true").lower() == "true"
    CELERY_ENABLED: bool = os.getenv("CELERY_ENABLED", "false").lower() == "true"
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    REFRESH_COOKIE_NAME: str = os.getenv("REFRESH_COOKIE_NAME", "forensic_refresh")
    REFRESH_COOKIE_SECURE: bool = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"
    REFRESH_COOKIE_SAMESITE: str = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").lower()
    CSRF_COOKIE_NAME: str = os.getenv("CSRF_COOKIE_NAME", "forensic_csrf")
    CSRF_COOKIE_SECURE: bool = os.getenv("CSRF_COOKIE_SECURE", "false").lower() == "true"
    CSRF_COOKIE_SAMESITE: str = os.getenv("CSRF_COOKIE_SAMESITE", "lax").lower()
    CALIBRATION_PATH: str = os.getenv("CALIBRATION_PATH", "backend/app/services/calibration.json")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if settings.PRODUCTION:
    if settings.DATABASE_URL.lower().startswith("sqlite"):
        raise RuntimeError("SQLite is not allowed in production mode.")

    insecure_values = {"change-this-in-production", "change-this-to-a-random-value", "changeme", "secret"}
    if settings.SECRET_KEY.strip().lower() in insecure_values or len(settings.SECRET_KEY.strip()) < 32:
        raise RuntimeError("SECRET_KEY must be a strong random value with at least 32 characters in production.")

    if not settings.REFRESH_COOKIE_SECURE:
        raise RuntimeError("REFRESH_COOKIE_SECURE must be true in production.")

    if settings.REFRESH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
        raise RuntimeError("REFRESH_COOKIE_SAMESITE must be one of: lax, strict, none.")

    if settings.CSRF_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
        raise RuntimeError("CSRF_COOKIE_SAMESITE must be one of: lax, strict, none.")

    if not settings.CSRF_COOKIE_SECURE:
        raise RuntimeError("CSRF_COOKIE_SECURE must be true in production.")

    if "*" in settings.ALLOWED_ORIGINS:
        raise RuntimeError("Wildcard CORS origin is not allowed in production.")
