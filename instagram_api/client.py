from __future__ import annotations

import logging
import re

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


class InstagramClient:
    async def get_media(self, url: str) -> InstagramMediaInfo:
        session = _get_http_session()
        api_key = config["instagram"]["rapidapi_key"]

        headers = {
            "X-Rapidapi-Key": api_key,
            "X-Rapidapi-Host": _RAPIDAPI_HOST,
        }
        api_url = f"https://{_RAPIDAPI_HOST}/convert"

        try:
            async with session.get(
                api_url, params={"url": url}, headers=headers
            ) as response:
                if response.status == 404:
                    raise InstagramNotFoundError("Post not found or private")
                if response.status == 429:
                    raise InstagramRateLimitError("API rate limit exceeded")
                if response.status != 200:
                    text = await response.text()
                    logger.error(
                        f"Instagram API error {response.status}: {text}"
                    )
                    raise InstagramNetworkError(
                        f"API returned status {response.status}"
                    )

                data = await response.json()
        except (InstagramNotFoundError, InstagramRateLimitError, InstagramNetworkError):
            raise
        except Exception as e:
            logger.error(f"Instagram API request failed: {e}")
            raise InstagramNetworkError(f"Request failed: {e}") from e

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

        return InstagramMediaInfo(media=media_items, link=url)
