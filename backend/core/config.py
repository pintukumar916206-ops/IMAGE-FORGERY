import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Image Forgery Detection System"
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./forgery.sqlite")
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "40"))
    SECURE_COOKIES: bool = os.getenv("SECURE_COOKIES", "False").lower() == "true"
    ALLOWED_ORIGINS: list = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    ).split(",")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
