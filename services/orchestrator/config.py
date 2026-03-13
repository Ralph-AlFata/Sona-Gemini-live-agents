"""Configuration for the Sona orchestrator service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Environment-backed settings for Gemini + service wiring."""

    google_genai_use_vertexai: bool = False
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    model_name: str = "gemini-live-2.5-flash-native-audio"
    chat_mode: Literal["auto", "gemini", "mock"] = "auto"
    app_name: str = "sona-orchestrator"
    default_user_id: str = "anonymous-user"
    default_session_id: str = "local-session"
    session_service_url: str = "http://session:8003"
    drawing_service_url: str = "http://drawing:8002"
    dedup_window_seconds: float = 2.0
    dedup_max_entries: int = 200
    orchestrator_auth_enabled: bool = False
    orchestrator_auth_audience: str = ""

    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
