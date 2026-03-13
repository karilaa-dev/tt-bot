"""TikTok-specific configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class TikTokSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TIKTOK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url_resolve_max_retries: int = 3
    video_info_max_retries: int = 3


@lru_cache
def get_tiktok_settings() -> TikTokSettings:
    return TikTokSettings()


tiktok_settings = get_tiktok_settings()
