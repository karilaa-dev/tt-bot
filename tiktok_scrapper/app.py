"""FastAPI REST API server for TikTok scrapping."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from .client import TikTokClient
from .config import config
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
from .models import (
    CheckResponse,
    ErrorResponse,
    HealthResponse,
    MusicDetailResponse,
    MusicResponse,
    RawMusicResponse,
    RawVideoResponse,
    VideoResponse,
)
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

# Map TikTok exceptions to HTTP status codes
_ERROR_STATUS_MAP: dict[type[TikTokError], int] = {
    TikTokDeletedError: 404,
    TikTokPrivateError: 403,
    TikTokInvalidLinkError: 400,
    TikTokVideoTooLongError: 413,
    TikTokRateLimitError: 429,
    TikTokNetworkError: 502,
    TikTokRegionError: 451,
    TikTokExtractionError: 500,
}

_client: TikTokClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client

    # Configure logging
    log_level = config.get("logging", {}).get("log_level", logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Initialize proxy manager
    proxy_config = config.get("proxy", {})
    proxy_file = proxy_config.get("proxy_file", "")
    proxy_manager = None
    if proxy_file:
        proxy_manager = ProxyManager.initialize(
            proxy_file,
            include_host=proxy_config.get("include_host", False),
        )

    # Initialize client
    _client = TikTokClient(
        proxy_manager=proxy_manager,
        data_only_proxy=proxy_config.get("data_only", False),
    )

    logger.info("TikTok scrapper API started")
    yield

    # Cleanup
    await TikTokClient.close_connector()
    await TikTokClient.close_curl_session()
    TikTokClient.shutdown_executor()
    logger.info("TikTok scrapper API stopped")


app = FastAPI(
    title="TikTok Scrapper API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(TikTokError)
async def tiktok_error_handler(request, exc: TikTokError):
    status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=str(exc),
            error_type=type(exc).__name__,
        ).model_dump(),
    )


def _build_filtered_video_response(
    video_data: dict[str, Any],
    video_id: int,
    link: str,
) -> VideoResponse:
    """Build a filtered VideoResponse from raw TikTok API data."""
    image_post = video_data.get("imagePost")
    video_info = video_data.get("video", {})
    stats = video_data.get("stats", {})

    # Extract music info if available
    music_data = video_data.get("music")
    music = None
    if music_data:
        music_url = music_data.get("playUrl")
        if music_url:
            music = MusicResponse(
                url=music_url,
                title=music_data.get("title", ""),
                author=music_data.get("authorName", ""),
                duration=int(music_data.get("duration", 0)),
                cover=(
                    music_data.get("coverLarge")
                    or music_data.get("coverMedium")
                    or music_data.get("coverThumb")
                    or ""
                ),
            )

    if image_post:
        # Slideshow
        images = image_post.get("images", [])
        image_urls = []
        for img in images:
            url_list = img.get("imageURL", {}).get("urlList", [])
            if url_list:
                image_urls.append(url_list[0])

        return VideoResponse(
            type="images",
            id=video_id,
            image_urls=image_urls,
            likes=stats.get("diggCount"),
            views=stats.get("playCount"),
            link=link,
            music=music,
        )

    # Video
    video_url = (
        video_info.get("playAddr")
        or video_info.get("downloadAddr")
    )
    if not video_url:
        # Try bitrateInfo
        for br in video_info.get("bitrateInfo", []):
            url_list = br.get("PlayAddr", {}).get("UrlList", [])
            if url_list:
                video_url = url_list[0]
                break

    duration = video_info.get("duration")
    if duration:
        duration = int(duration)

    width = video_info.get("width")
    height = video_info.get("height")
    cover = video_info.get("cover") or video_info.get("originCover")

    return VideoResponse(
        type="video",
        id=video_id,
        video_url=video_url,
        cover=cover,
        width=int(width) if width else None,
        height=int(height) if height else None,
        duration=duration,
        likes=stats.get("diggCount"),
        views=stats.get("playCount"),
        link=link,
        music=music,
    )


@app.get("/video", response_model=VideoResponse | RawVideoResponse)
async def get_video(
    url: str = Query(..., description="TikTok video or slideshow URL"),
    raw: bool = Query(False, description="Return raw TikTok API data"),
):
    """Extract video/slideshow info from a TikTok URL.

    With raw=false (default): returns filtered metadata with CDN URLs.
    With raw=true: returns the full TikTok API response dict.
    """
    result = await _client.extract_video_info(url)
    video_data = result["video_data"]
    video_id = int(result["video_id"])
    resolved_url = result["resolved_url"]

    if raw:
        return RawVideoResponse(
            id=video_id,
            resolved_url=resolved_url,
            data=video_data,
        )

    return _build_filtered_video_response(video_data, video_id, url)


@app.get("/music", response_model=MusicDetailResponse | RawMusicResponse)
async def get_music(
    video_id: int = Query(..., description="TikTok video ID"),
    raw: bool = Query(False, description="Return raw TikTok API data"),
):
    """Extract music info from a TikTok video.

    With raw=false (default): returns filtered music metadata with CDN URL.
    With raw=true: returns the full music data from TikTok API.
    """
    result = await _client.extract_music_info(video_id)
    music_data = result["music_data"]

    if raw:
        return RawMusicResponse(
            id=video_id,
            data=result["video_data"],
        )

    music_url = music_data.get("playUrl", "")
    cover = (
        music_data.get("coverLarge")
        or music_data.get("coverMedium")
        or music_data.get("coverThumb")
        or ""
    )

    return MusicDetailResponse(
        id=video_id,
        title=music_data.get("title", ""),
        author=music_data.get("authorName", ""),
        duration=int(music_data.get("duration", 0)),
        cover=cover,
        url=music_url,
    )


@app.get("/check", response_model=CheckResponse)
async def check_url(
    url: str = Query(..., description="URL to validate"),
):
    """Quick regex validation of a TikTok URL (no network calls)."""
    matched_url, is_mobile = await _client.regex_check(url)
    return CheckResponse(
        valid=matched_url is not None,
        url=matched_url,
        is_mobile=is_mobile,
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse()
