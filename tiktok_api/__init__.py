"""TikTok API client for extracting video and music information.

This module provides a clean interface to extract TikTok video/slideshow data
and music information using curl_cffi with browser impersonation.

Example:
    >>> from tiktok_api import TikTokClient, ProxyManager, VideoInfo, TikTokDeletedError
    >>>
    >>> # Initialize proxy manager (optional)
    >>> proxy_manager = ProxyManager.initialize("proxies.txt", include_host=True)
    >>>
    >>> client = TikTokClient(proxy_manager=proxy_manager, data_only_proxy=True)
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
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
)
from .models import MusicInfo, VideoInfo
from .proxy_manager import ProxyManager

__all__ = [
    # Client
    "TikTokClient",
    "ttapi",  # Backwards compatibility alias
    # Proxy
    "ProxyManager",
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
    "TikTokInvalidLinkError",
    "TikTokVideoTooLongError",
]
