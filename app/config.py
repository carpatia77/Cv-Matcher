from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    APP_ENV: str = "development"

    TURNSTILE_SECRET_KEY: str = ""
    TURNSTILE_SITE_KEY: str = ""

    TIMEOUT_EXTRACTION: float = 20.0
    TIMEOUT_OPTIMIZATION: float = 90.0
    TIMEOUT_EMBEDDING: float = 30.0
    TIMEOUT_AUDIT: float = 120.0
    TIMEOUT_PDF: float = 30.0
    HTTPX_TIMEOUT: float = 240.0
    AUDIT_MAX_TOKENS: int = 4096
    MAX_UPLOAD_MB: int = 10
    GLOBAL_LLM_CALLS_PER_MINUTE: int = 5
    MAX_DAILY_LLM_CALLS: int = 100

    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/ats.db"

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

settings = Settings()
