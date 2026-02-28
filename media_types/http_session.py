import asyncio
import logging

import aiohttp
from aiohttp import ClientTimeout
from aiogram.types import BufferedInputFile
from yarl import URL

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
            headers={"User-Agent": "Mozilla/5.0"},
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
    logger.debug(f"Starting download: {url} (max_retries={max_retries})")
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"Attempt {attempt}/{max_retries}: GET {url}")
            async with session.get(URL(url, encoded=True), allow_redirects=True) as response:
                logger.debug(
                    f"Response {response.status} for {url} "
                    f"(attempt {attempt}/{max_retries}, "
                    f"content-type={response.content_type}, "
                    f"content-length={response.headers.get('Content-Length', 'unknown')})"
                )
                if response.status == 200:
                    data = await response.read()
                    logger.debug(f"Downloaded {len(data)} bytes from {url}")
                    return data
                if response.status not in _RETRYABLE_STATUSES:
                    body = await response.text()
                    logger.warning(
                        f"Non-retryable status {response.status} for {url}: {body[:500]}"
                    )
                    return None
                logger.warning(
                    f"Retryable status {response.status} (attempt {attempt}/{max_retries}): {url}"
                )
        except Exception as e:
            logger.warning(
                f"Download exception (attempt {attempt}/{max_retries}): {url}: {type(e).__name__}: {e}"
            )
        if attempt < max_retries:
            logger.debug(f"Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
    logger.error(f"All {max_retries} attempts failed for {url}")
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
