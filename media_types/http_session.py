import logging

import aiohttp
from aiohttp import ClientTimeout
from aiogram.types import BufferedInputFile

from data.config import config

logger = logging.getLogger(__name__)

# Storage channel for uploading videos to get file_id (required for inline messages)
STORAGE_CHANNEL_ID = config["bot"].get("storage_channel")

# Shared aiohttp session for cover/thumbnail downloads
# Reusing sessions is more efficient than creating new ones per request
_http_session: aiohttp.ClientSession | None = None

# Timeout configuration for HTTP requests
_HTTP_TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=20)


def _get_http_session() -> aiohttp.ClientSession:
    """Get or create a shared aiohttp ClientSession for HTTP requests.

    The session is configured with:
    - 30s total timeout (prevents hanging requests)
    - 10s connect timeout
    - 20s read timeout
    """
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=20,  # Per-host limit to avoid overwhelming single CDN
            ttl_dns_cache=300,  # Cache DNS for 5 minutes
            enable_cleanup_closed=True,
        )
        _http_session = aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT,
            connector=connector,
        )
    return _http_session


async def close_http_session() -> None:
    """Close the shared aiohttp session. Call on application shutdown."""
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        _http_session = None


async def _download_url(url: str) -> bytes | None:
    """Download content from a URL using the shared HTTP session.

    Returns:
        Downloaded bytes or None if the download failed
    """
    try:
        session = _get_http_session()
        async with session.get(url, allow_redirects=True) as response:
            if response.status == 200:
                return await response.read()
    except Exception as e:
        logger.warning(f"Failed to download from {url}: {e}")
    return None


async def download_thumbnail(
    cover_url: str | None, video_id: int
) -> BufferedInputFile | None:
    """Download cover image for use as video thumbnail.

    Only used for videos longer than 1 minute to provide a proper preview.
    """
    if not cover_url:
        return None
    cover_bytes = await _download_url(cover_url)
    if cover_bytes:
        return BufferedInputFile(cover_bytes, f"{video_id}_thumb.jpg")
    return None
