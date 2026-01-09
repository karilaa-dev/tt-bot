"""TikTok API client for extracting video and music information.

This module provides a clean interface to extract TikTok video/slideshow data
and music information using yt-dlp internally.

Example:
    >>> from tiktok_api import TikTokClient, VideoInfo, TikTokDeletedError
    >>>
    >>> client = TikTokClient(proxy="http://proxy:8080")
    >>> try:
    ...     video_info = await client.video("https://www.tiktok.com/@user/video/123")
    ...     print(video_info.author)
    ...     print(video_info.id)
    ...     if video_info.is_video:
    ...         print(f"Duration: {video_info.duration}s")
    ... except TikTokDeletedError:
    ...     print("Video was deleted")
"""

from .client import TikTokClient, ttapi
from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
)
from .models import MusicInfo, VideoInfo

__all__ = [
    # Client
    "TikTokClient",
    "ttapi",  # Backwards compatibility alias
    # Models
    "VideoInfo",
    "MusicInfo",
    # Exceptions
    "TikTokError",
    "TikTokDeletedError",
    "TikTokPrivateError",
    "TikTokNetworkError",
    "TikTokRateLimitError",
    "TikTokRegionError",
    "TikTokExtractionError",
]
