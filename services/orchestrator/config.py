from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str = ""
    drawing_service_url: str = "http://localhost:8002"
    session_service_url: str = "http://localhost:8003"
    model_name: str = "gemini-2.5-flash-native-audio-preview-12-2025"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
