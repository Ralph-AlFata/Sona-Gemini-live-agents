"""Configuration for the Sona Drawing Command Service."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for the drawing service."""

    frontend_url: str = ""
    port: int = 8002
    use_firestore: bool = False
    firestore_database: str = "(default)"
    google_cloud_project: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
