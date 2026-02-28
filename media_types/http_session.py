import logging

import aiohttp
from aiohttp import ClientTimeout
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

_http_session: aiohttp.ClientSession | None = None
_HTTP_TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=20)


def _get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=20,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        _http_session = aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT,
            connector=connector,
        )
    return _http_session


async def close_http_session() -> None:
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        _http_session = None


async def _download_url(url: str) -> bytes | None:
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
    if not cover_url:
        return None
    cover_bytes = await _download_url(cover_url)
    if cover_bytes:
        return BufferedInputFile(cover_bytes, f"{video_id}_thumb.jpg")
    return None
