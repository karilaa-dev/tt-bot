from __future__ import annotations

import asyncio
import logging
import re

from aiohttp import ClientTimeout

from data.config import config
from media_types.http_session import _get_http_session

from .exceptions import (
    InstagramNetworkError,
    InstagramNotFoundError,
    InstagramRateLimitError,
)
from .models import InstagramMediaInfo, InstagramMediaItem

logger = logging.getLogger(__name__)

INSTAGRAM_URL_REGEX = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reels?|reel|tv|stories)/[\w-]+",
    re.IGNORECASE,
)

_RAPIDAPI_HOST = (
    "instagram-downloader-download-instagram-stories-videos4.p.rapidapi.com"
)

_MAX_ATTEMPTS = 3
_RETRY_DELAYS = (3, 5)
_REQUEST_TIMEOUT = ClientTimeout(total=10, connect=3)


class InstagramClient:
    async def get_media(self, url: str) -> InstagramMediaInfo:
        session = _get_http_session()
        api_key = config["instagram"]["rapidapi_key"]

        headers = {
            "X-Rapidapi-Key": api_key,
            "X-Rapidapi-Host": _RAPIDAPI_HOST,
        }
        api_url = f"https://{_RAPIDAPI_HOST}/convert"

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with session.get(
                    api_url,
                    params={"url": url},
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                ) as response:
                    if response.status == 404:
                        raise InstagramNotFoundError("Post not found or private")
                    if response.status == 429:
                        raise InstagramRateLimitError("API rate limit exceeded")
                    if response.status >= 500:
                        raise InstagramNetworkError(
                            f"API returned status {response.status}"
                        )
                    if response.status != 200:
                        text = await response.text()
                        logger.error(
                            f"Instagram API error {response.status}: {text}"
                        )
                        raise InstagramNetworkError(
                            f"API returned status {response.status}"
                        )

                    data = await response.json()
                    logger.debug(f"Instagram API response keys: {list(data.keys())}")
                    logger.debug(
                        f"Instagram API media count: {len(data.get('media', []))}"
                    )
                    for i, item in enumerate(data.get("media", [])):
                        logger.debug(
                            f"  media[{i}]: type={item.get('type')}, "
                            f"url={item.get('url', '')[:120]}, "
                            f"thumbnail={str(item.get('thumbnail', ''))[:120]}, "
                            f"quality={item.get('quality')}"
                        )
                    break  # success
            except InstagramNotFoundError:
                raise
            except (InstagramRateLimitError, InstagramNetworkError) as e:
                last_exc = e
            except Exception as e:
                last_exc = InstagramNetworkError(f"Request failed: {e}")
                last_exc.__cause__ = e

            if attempt < _MAX_ATTEMPTS:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "Instagram API attempt %d/%d failed: %s — retrying in %ds",
                    attempt,
                    _MAX_ATTEMPTS,
                    last_exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Instagram API attempt %d/%d failed: %s — giving up",
                    attempt,
                    _MAX_ATTEMPTS,
                    last_exc,
                )
                raise last_exc  # type: ignore[misc]

        media_items = []
        for item in data.get("media", []):
            media_items.append(
                InstagramMediaItem(
                    type=item.get("type", "image"),
                    url=item["url"],
                    thumbnail=item.get("thumbnail"),
                    quality=item.get("quality"),
                )
            )

        if not media_items:
            raise InstagramNotFoundError("No media found in response")

        result = InstagramMediaInfo(media=media_items, link=url)
        logger.debug(
            f"InstagramMediaInfo: is_video={result.is_video}, "
            f"video_url={str(result.video_url or '')[:120]}, "
            f"thumbnail_url={str(result.thumbnail_url or '')[:120]}, "
            f"media_count={len(result.media)}"
        )
        return result
