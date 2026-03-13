"""Music extraction endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..client import TikTokClient
from ..dependencies import get_client
from ..models import MusicDetailResponse, RawMusicResponse

router = APIRouter()


@router.get("/music", response_model=MusicDetailResponse | RawMusicResponse)
async def get_music(
    video_id: int = Query(..., description="TikTok video ID"),
    raw: bool = Query(False, description="Return raw TikTok API data"),
    client: TikTokClient = Depends(get_client),
):
    """Extract music info from a TikTok video."""
    result = await client.extract_music_info(video_id)
    music_data = result["music_data"]

    if raw:
        return RawMusicResponse(
            id=video_id,
            data=result["video_data"],
        )

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
        url=music_data.get("playUrl", ""),
    )
