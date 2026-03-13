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
    proxy_include_host: bool = False

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
