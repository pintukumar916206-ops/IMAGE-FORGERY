import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

class Settings(BaseSettings):
    @model_validator(mode="after")
    def check_dev_secret_key(self) -> 'Settings':
        debug_mode = os.getenv("DEBUG", "False").strip().lower() == "true"
        if not debug_mode and "dev-secret-key" in self.SECRET_KEY:
            raise ValueError("SECURITY PANIC: Refusing to start in PRODUCTION with the default 'dev-secret-key'. You must generate a secure SECRET_KEY.")
        return self

    ELA_THRESHOLD: float = float(os.getenv("ELA_THRESHOLD", "25.0"))

    ELA_JPEG_QUALITY: int = int(os.getenv("ELA_JPEG_QUALITY", "90"))

    SIFT_RATIO_THRESHOLD: float = float(os.getenv("SIFT_RATIO_THRESHOLD", "0.65"))
    SIFT_MIN_MATCHES: int = int(os.getenv("SIFT_MIN_MATCHES", "10"))
    SIFT_MIN_INLIERS: int = int(os.getenv("SIFT_MIN_INLIERS", "5"))
    SIFT_CLUSTER_DISTANCE: float = float(os.getenv("SIFT_CLUSTER_DISTANCE", "2.2"))
    SIFT_MIN_SPATIAL_DISTANCE: int = int(os.getenv("SIFT_MIN_SPATIAL_DISTANCE", "20"))
    SIFT_MAX_SPATIAL_DISTANCE: int = int(os.getenv("SIFT_MAX_SPATIAL_DISTANCE", "500"))

    WEIGHT_EXIF: float = float(os.getenv("WEIGHT_EXIF", "0.20"))
    WEIGHT_ELA: float = float(os.getenv("WEIGHT_ELA", "0.30"))
    WEIGHT_SIFT: float = float(os.getenv("WEIGHT_SIFT", "0.30"))
    WEIGHT_ML: float = float(os.getenv("WEIGHT_ML", "0.20"))

    ENTROPY_THRESHOLD: float = float(os.getenv("ENTROPY_THRESHOLD", "5.0"))

    API_KEY_REQUIRED: bool = _to_bool(os.getenv("API_KEY_REQUIRED"), default=True)
    SECRET_KEY: str
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str
    ANALYST_USERNAME: str = os.getenv("ANALYST_USERNAME", "analyst")
    ANALYST_PASSWORD: str

    SYNC_MODE: bool = _to_bool(os.getenv("SYNC_MODE"), default=False)
    REPORT_EXPIRATION_HOURS: int = int(os.getenv("REPORT_EXPIRATION_HOURS", "24"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
    )

settings = Settings()
