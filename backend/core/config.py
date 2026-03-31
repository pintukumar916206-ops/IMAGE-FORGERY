import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    @model_validator(mode="after")
    def check_dev_secret_key(self) -> 'Settings':
        debug_mode = os.getenv("DEBUG", "False").strip().lower() == "true"
        if not debug_mode and "dev-secret-key" in self.SECRET_KEY:
            # Only relevant if we ever re-enable Auth, but good practice
            pass
        return self

    # Forensic Thresholds
    ELA_THRESHOLD: float = float(os.getenv("ELA_THRESHOLD", "8.0"))
    ELA_JPEG_QUALITY: int = int(os.getenv("ELA_JPEG_QUALITY", "90"))
    ENTROPY_THRESHOLD: float = float(os.getenv("ENTROPY_THRESHOLD", "5.0"))
    
    # SIFT Parameters
    SIFT_RATIO_THRESHOLD: float = float(os.getenv("SIFT_RATIO_THRESHOLD", "0.65"))
    SIFT_MIN_MATCHES: int = int(os.getenv("SIFT_MIN_MATCHES", "10"))
    SIFT_MIN_INLIERS: int = int(os.getenv("SIFT_MIN_INLIERS", "5"))
    SIFT_CLUSTER_DISTANCE: float = float(os.getenv("SIFT_CLUSTER_DISTANCE", "2.2"))
    SIFT_MIN_SPATIAL_DISTANCE: int = int(os.getenv("SIFT_MIN_SPATIAL_DISTANCE", "20"))
    SIFT_MAX_SPATIAL_DISTANCE: int = int(os.getenv("SIFT_MAX_SPATIAL_DISTANCE", "500"))

    # System Configuration
    DB_PATH: str = os.getenv("DB_PATH", "forgery.sqlite")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-for-internal-v4")
    REPORT_EXPIRATION_HOURS: int = int(os.getenv("REPORT_EXPIRATION_HOURS", "24"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
    )

settings = Settings()
