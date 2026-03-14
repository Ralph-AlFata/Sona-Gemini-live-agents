"""Configuration for the Sona Drawing Command Service."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_SERVICE_DIR = Path(__file__).resolve().parent
# Walk up looking for a root .env (dev convenience). In Docker /app has no parent .env
# so we collect only paths that actually exist to avoid IndexError.
_candidate_env_files: list[str] = []
for _p in (_SERVICE_DIR.parent.parent / ".env", _SERVICE_DIR / ".env"):
    _candidate_env_files.append(str(_p))  # pydantic-settings ignores missing files


class Settings(BaseSettings):
    """Environment-backed settings for the drawing service."""

    frontend_url: str = ""
    port: int = 8002
    use_firestore: bool = False
    firestore_database: str = "(default)"
    google_cloud_project: str = ""
    drawing_auth_enabled: bool = False
    drawing_auth_audience: str = ""
    session_service_url: str = "http://session:8003"

    model_config = SettingsConfigDict(
        env_file=tuple(_candidate_env_files),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
