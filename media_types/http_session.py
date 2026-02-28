import asyncio
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


_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def _download_url(
    url: str, max_retries: int = 3, retry_delay: float = 1.0
) -> bytes | None:
    session = _get_http_session()
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status == 200:
                    return await response.read()
                if response.status not in _RETRYABLE_STATUSES:
                    logger.warning(f"Download returned {response.status}: {url}")
                    return None
                logger.warning(
                    f"Download returned {response.status} (attempt {attempt}/{max_retries}): {url}"
                )
        except Exception as e:
            logger.warning(
                f"Download failed (attempt {attempt}/{max_retries}): {url}: {e}"
            )
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)
    return None


async def download_thumbnail(
    cover_url: str | None, video_id: int
) -> BufferedInputFile | None:
    if not cover_url:
        return None
    cover_bytes = await _download_url(cover_url, max_retries=1)
    if cover_bytes:
        return BufferedInputFile(cover_bytes, f"{video_id}_thumb.jpg")
    return None
