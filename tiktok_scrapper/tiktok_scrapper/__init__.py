"""TikTok scrapper - standalone REST API for TikTok metadata extraction."""

from .client import TikTokClient
from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
)
from .proxy_manager import ProxyManager

__all__ = [
    "TikTokClient",
    "ProxyManager",
    "TikTokError",
    "TikTokDeletedError",
    "TikTokInvalidLinkError",
    "TikTokPrivateError",
    "TikTokNetworkError",
    "TikTokRateLimitError",
    "TikTokRegionError",
    "TikTokExtractionError",
    "TikTokVideoTooLongError",
]
