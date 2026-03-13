"""TikTok scrapper - standalone TikTok video/music/slideshow extraction.

Example:
    >>> from tiktok_scrapper import TikTokClient, ProxyManager, VideoInfo
    >>>
    >>> proxy_manager = ProxyManager.initialize("proxies.txt", include_host=True)
    >>> client = TikTokClient(proxy_manager=proxy_manager, data_only_proxy=True)
    >>> video_info = await client.video("https://www.tiktok.com/@user/video/123")
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
    "ttapi",
    # Proxy
    "ProxyManager",
    # Models
    "VideoInfo",
    "MusicInfo",
    # Exceptions
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
