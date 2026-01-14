"""Data models for TikTok API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class VideoInfo:
    """Information about a TikTok video or slideshow.

    Attributes:
        type: Content type - "video" for videos, "images" for slideshows
        data: Video bytes (for videos) or list of image URLs (for slideshows)
        id: Unique TikTok video/post ID
        cover: Thumbnail/cover image URL (only for videos > 1 minute)
        width: Video width in pixels (only for videos > 1 minute)
        height: Video height in pixels (only for videos > 1 minute)
        duration: Video duration in seconds (None for slideshows)
        author: Author's username
        link: Original TikTok link
        url: Direct video URL (only present for videos, None for slideshows)
    """

    type: str  # "video" or "images"
    data: Union[bytes, List[str]]  # video bytes OR list of image URLs
    id: int
    cover: Optional[str]
    width: Optional[int]
    height: Optional[int]
    duration: Optional[int]
    author: str
    link: str
    url: Optional[str] = None  # Only present for videos

    # Proxy used for this video extraction (for slideshow image downloads)
    # This allows image downloads to use the same proxy that successfully
    # extracted the video info.
    _proxy: Optional[str] = field(default=None, repr=False)

    @property
    def is_video(self) -> bool:
        """Check if this is a video (not a slideshow)."""
        return self.type == "video"

    @property
    def is_slideshow(self) -> bool:
        """Check if this is a slideshow (image post)."""
        return self.type == "images"

    @property
    def image_urls(self) -> List[str]:
        """Get list of image URLs (only for slideshows).

        Returns:
            List of image URLs if this is a slideshow, empty list otherwise.
        """
        if self.type == "images" and isinstance(self.data, list):
            return self.data
        return []

    @property
    def video_bytes(self) -> Optional[bytes]:
        """Get video bytes (only for videos).

        Returns:
            Video bytes if this is a video, None otherwise.
        """
        if self.type == "video" and isinstance(self.data, bytes):
            return self.data
        return None


@dataclass
class MusicInfo:
    """Information about TikTok music/audio.

    Attributes:
        data: Audio file bytes
        id: Video ID from which the music was extracted
        title: Music/sound title
        author: Music author/artist name
        duration: Audio duration in seconds
        cover: Cover image URL for the music
    """

    data: bytes
    id: int
    title: str
    author: str
    duration: int
    cover: str
