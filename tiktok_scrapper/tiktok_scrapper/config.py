"""Configuration for TikTok scrapper API using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Retry
    url_resolve_max_retries: int = 3
    video_info_max_retries: int = 3

    # Proxy
    proxy_file: str = ""
    proxy_data_only: bool = False
    proxy_include_host: bool = False

    # Performance
    max_video_duration: int = 0
    streaming_duration_threshold: int = 300

    # Logging
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
