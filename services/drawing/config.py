"""Configuration for the Sona Drawing Command Service."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
        env_file=(str(_ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
