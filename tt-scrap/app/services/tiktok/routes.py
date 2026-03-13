"""TikTok API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from ...exceptions import ExtractionError
from ...models import (
    MusicDetailResponse,
    RawMusicResponse,
    RawVideoResponse,
    VideoResponse,
)
from .parser import build_music_response, build_video_response

if TYPE_CHECKING:
    from .client import TikTokClient

router = APIRouter(prefix="/tiktok", tags=["tiktok"])

_client: "TikTokClient | None" = None


def set_client(client: "TikTokClient") -> None:
    global _client
    _client = client


def _get_client() -> "TikTokClient":
    assert _client is not None, "TikTok client not initialized"
    return _client


@router.get("/video", response_model=VideoResponse | RawVideoResponse)
async def get_video(
    url: str = Query(..., description="TikTok video or slideshow URL"),
    raw: bool = Query(False, description="Return raw TikTok API data"),
):
    """Extract video/slideshow info from a TikTok URL."""
    client = _get_client()
    result = await client.extract_video_info(url)
    video_data = result["video_data"]
    video_id = int(result["video_id"])
    resolved_url = result["resolved_url"]

    if raw:
        return RawVideoResponse(
            id=video_id,
            resolved_url=resolved_url,
            data=video_data,
        )

    return build_video_response(video_data, video_id, url)


@router.get("/music", response_model=MusicDetailResponse | RawMusicResponse)
async def get_music(
    video_id: int = Query(..., description="TikTok video ID"),
    raw: bool = Query(False, description="Return raw TikTok API data"),
):
    """Extract music info from a TikTok video."""
    client = _get_client()
    result = await client.extract_music_info(video_id)

    if result is None:
        raise ExtractionError("Music extraction not available")

    music_data = result["music_data"]

    if raw:
        return RawMusicResponse(
            id=video_id,
            data=result["video_data"],
        )

    return build_music_response(music_data, video_id)
