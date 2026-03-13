"""Compatibility shim - re-exports from tiktok_scrapper package."""

from tiktok_scrapper import (
    MusicInfo,
    ProxyManager,
    TikTokClient,
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
    VideoInfo,
    ttapi,
)

__all__ = [
    "TikTokClient",
    "ttapi",
    "ProxyManager",
    "VideoInfo",
    "MusicInfo",
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
