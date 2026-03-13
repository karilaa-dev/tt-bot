"""TikTok-specific response parsing."""

from __future__ import annotations

from typing import Any

from ...models import MusicDetailResponse, MusicResponse, VideoResponse


def build_video_response(
    video_data: dict[str, Any],
    video_id: int,
    link: str,
) -> VideoResponse:
    image_post = video_data.get("imagePost")
    video_info = video_data.get("video", {})
    stats = video_data.get("stats", {})

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
        image_urls = [
            url_list[0]
            for img in image_post.get("images", [])
            if (url_list := img.get("imageURL", {}).get("urlList", []))
        ]

        return VideoResponse(
            type="images",
            id=video_id,
            image_urls=image_urls,
            likes=stats.get("diggCount"),
            views=stats.get("playCount"),
            link=link,
            music=music,
        )

    video_url = video_info.get("playAddr") or video_info.get("downloadAddr")
    if not video_url:
        for br in video_info.get("bitrateInfo", []):
            url_list = br.get("PlayAddr", {}).get("UrlList", [])
            if url_list:
                video_url = url_list[0]
                break

    raw_duration = video_info.get("duration")
    raw_width = video_info.get("width")
    raw_height = video_info.get("height")
    cover = video_info.get("cover") or video_info.get("originCover")

    return VideoResponse(
        type="video",
        id=video_id,
        video_url=video_url,
        cover=cover,
        width=int(raw_width) if raw_width else None,
        height=int(raw_height) if raw_height else None,
        duration=int(raw_duration) if raw_duration else None,
        likes=stats.get("diggCount"),
        views=stats.get("playCount"),
        link=link,
        music=music,
    )


def build_music_response(
    music_data: dict[str, Any],
    video_id: int,
) -> MusicDetailResponse:
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
