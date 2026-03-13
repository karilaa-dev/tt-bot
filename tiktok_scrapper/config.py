"""Standalone configuration for TikTok scrapper.

Reads all settings from environment variables. No dependency on the bot's config.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


def _parse_int_env(key: str, default: int) -> int:
    value = os.getenv(key, "")
    if value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _parse_bool_env(key: str, default: bool = False) -> bool:
    value = os.getenv(key, "")
    if value.strip():
        return value.strip().lower() == "true"
    return default


def _parse_log_level(key: str, default: str = "INFO") -> int:
    value = os.getenv(key, default).upper().strip()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(value, logging.INFO)


config = {
    "retry": {
        "url_resolve_max_retries": _parse_int_env("URL_RESOLVE_MAX_RETRIES", 3),
        "video_info_max_retries": _parse_int_env("VIDEO_INFO_MAX_RETRIES", 3),
        "download_max_retries": _parse_int_env("DOWNLOAD_MAX_RETRIES", 3),
    },
    "proxy": {
        "proxy_file": os.getenv("PROXY_FILE", ""),
        "data_only": _parse_bool_env("PROXY_DATA_ONLY"),
        "include_host": _parse_bool_env("PROXY_INCLUDE_HOST"),
    },
    "performance": {
        "streaming_duration_threshold": _parse_int_env("STREAMING_DURATION_THRESHOLD", 300),
        "max_video_duration": _parse_int_env("MAX_VIDEO_DURATION", 0),
    },
    "logging": {
        "log_level": _parse_log_level("LOG_LEVEL", "INFO"),
    },
    "server": {
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": _parse_int_env("PORT", 8000),
    },
}
