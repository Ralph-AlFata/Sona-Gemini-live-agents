"""Configuration for the Sona orchestrator service."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for Gemini + service wiring."""

    google_genai_use_vertexai: bool = False
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    model_name: str = "gemini-live-2.5-flash-native-audio"
    app_name: str = "sona-orchestrator"
    default_user_id: str = "anonymous-user"
    default_session_id: str = "local-session"
    session_service_url: str = "http://session:8003"
    drawing_service_url: str = "http://drawing:8002"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
