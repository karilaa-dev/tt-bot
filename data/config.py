from __future__ import annotations

import os
from json import loads as json_loads
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


def _parse_int_env(key: str, default: int) -> int:
    """Parse an environment variable as an integer, returning default if unset/empty."""
    value = os.getenv(key, "")
    if value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _parse_int_env_optional(key: str) -> int | None:
    """Parse an environment variable as an integer, returning None if unset/empty."""
    value = os.getenv(key, "")
    if value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_json_list(key: str) -> list[int]:
    """Parse an environment variable as a JSON list of integers."""
    raw = os.getenv(key, "[]")
    try:
        result = json_loads(raw)
        if isinstance(result, list):
            return [int(item) for item in result]
        return []
    except (ValueError, TypeError):
        return []


class BotConfig(TypedDict):
    """Type definition for bot configuration."""

    token: str
    stats_token: str
    admin_ids: list[int]
    second_ids: list[int]
    stats_ids: list[int]
    tg_server: str
    db_url: str
    storage_channel: int | None


class ApiConfig(TypedDict):
    """Type definition for API configuration."""

    botstat: str
    monetag_url: str


class LogsConfig(TypedDict):
    """Type definition for logs configuration."""

    join_logs: str
    stats_chat: str
    stats_message_id: str
    daily_stats_message_id: str


class QueueConfig(TypedDict):
    """Type definition for queue and retry configuration."""

    max_user_queue_size: int
    retry_max_attempts: int
    retry_request_timeout: float


class ProxyConfig(TypedDict):
    """Type definition for proxy configuration."""

    proxy_file: str  # Path to proxy list file (one URL per line)
    data_only: bool  # Use proxy only for API, not media downloads
    include_host: bool  # Include host IP in round-robin rotation


class PerformanceConfig(TypedDict):
    """Type definition for performance configuration."""

    thread_pool_size: int  # ThreadPoolExecutor workers for sync yt-dlp calls
    aiohttp_pool_size: int  # Total aiohttp connection pool size (legacy, for redirects)
    aiohttp_limit_per_host: int  # Per-host connection limit
    max_concurrent_images: int  # Max parallel image downloads per slideshow
    curl_pool_size: int  # curl_cffi max_clients for media downloads
    streaming_duration_threshold: (
        int  # Use streaming for videos longer than this (seconds)
    )
    max_video_duration: int  # Maximum video duration in seconds (0 = no limit)


class Config(TypedDict):
    """Type definition for the main configuration."""

    bot: BotConfig
    api: ApiConfig
    logs: LogsConfig
    queue: QueueConfig
    proxy: ProxyConfig
    performance: PerformanceConfig


config: Config = {
    "bot": {
        "token": os.getenv("BOT_TOKEN", ""),
        "stats_token": os.getenv("STATS_BOT_TOKEN", ""),
        "admin_ids": _parse_json_list("ADMIN_IDS"),
        "second_ids": _parse_json_list("SECOND_IDS"),
        "stats_ids": _parse_json_list("STATS_IDS"),
        "tg_server": os.getenv("TG_SERVER", "https://api.telegram.org"),
        "db_url": os.getenv("DB_URL", ""),
        # Channel ID for uploading videos to get file_id.
        # Parsed as int; returns None if unset/empty. Callers using send_video/send_document
        # must check for None before using this value.
        "storage_channel": _parse_int_env_optional("STORAGE_CHANNEL_ID"),
    },
    "api": {
        "botstat": os.getenv("BOTSTAT", ""),
        "monetag_url": os.getenv("MONETAG_URL", ""),
    },
    "logs": {
        "join_logs": os.getenv("JOIN_LOGS", "0"),
        "stats_chat": os.getenv("STATS_CHAT", "0"),
        "stats_message_id": os.getenv("STATS_MESSAGE_ID", "0"),
        "daily_stats_message_id": os.getenv("DAILY_STATS_MESSAGE_ID", "0"),
    },
    "queue": {
        "max_user_queue_size": _parse_int_env("MAX_USER_QUEUE_SIZE", 3),
        "retry_max_attempts": _parse_int_env("RETRY_MAX_ATTEMPTS", 3),
        "retry_request_timeout": float(os.getenv("RETRY_REQUEST_TIMEOUT", "10")),
    },
    "proxy": {
        "proxy_file": os.getenv("PROXY_FILE", ""),
        "data_only": os.getenv("PROXY_DATA_ONLY", "false").lower() == "true",
        "include_host": os.getenv("PROXY_INCLUDE_HOST", "false").lower() == "true",
    },
    "performance": {
        "thread_pool_size": _parse_int_env("THREAD_POOL_SIZE", 128),
        "aiohttp_pool_size": _parse_int_env("AIOHTTP_POOL_SIZE", 200),
        "aiohttp_limit_per_host": _parse_int_env("AIOHTTP_LIMIT_PER_HOST", 50),
        "max_concurrent_images": _parse_int_env("MAX_CONCURRENT_IMAGES", 20),
        "curl_pool_size": _parse_int_env("CURL_POOL_SIZE", 200),
        "streaming_duration_threshold": _parse_int_env(
            "STREAMING_DURATION_THRESHOLD", 300
        ),
        "max_video_duration": _parse_int_env("MAX_VIDEO_DURATION", 1800),  # 30 minutes
    },
}

admin_ids: list[int] = config["bot"]["admin_ids"]
second_ids: list[int] = admin_ids + config["bot"]["second_ids"]
stats_ids: list[int] = config["bot"]["stats_ids"]
monetag_url: str = config["api"]["monetag_url"]

# Locale dictionary: maps language codes to their translation dictionaries
locale: dict[str, Any] = {}
_base_dir = Path(__file__).resolve().parent
_locale_dir = _base_dir / "locale"
locale["langs"] = sorted(
    file.replace(".json", "")
    for file in os.listdir(_locale_dir)
    if file.endswith(".json")
)
for _lang in locale["langs"]:
    with open(_locale_dir / f"{_lang}.json", "r", encoding="utf-8") as _locale_file:
        locale[_lang] = json_loads(_locale_file.read())
