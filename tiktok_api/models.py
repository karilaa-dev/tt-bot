"""Data models for TikTok API responses."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """Information about a TikTok video or slideshow.

    Attributes:
        type: Content type - "video" for videos, "images" for slideshows
        data: Video bytes (for videos) or list of image URLs (for slideshows)
        id: Unique TikTok video/post ID
        cover: Thumbnail/cover image URL
        width: Video width in pixels (None for slideshows)
        height: Video height in pixels (None for slideshows)
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

    # Download context for slideshows (set by TikTokClient).
    # Contains yt-dlp YoutubeDL instance and TikTok extractor with cookies/auth
    # already configured from the extraction phase. This allows image downloads
    # to use the same authentication context as the video info extraction.
    # Structure: {'ydl': YoutubeDL, 'ie': TikTokIE, 'referer_url': str}
    _download_context: Optional[dict[str, Any]] = field(default=None, repr=False)

    # Track whether close() was called to avoid double-close and __del__ warnings
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        """Close the download context and release resources.

        Call this method when you're done using the VideoInfo,
        especially for slideshows where the download context is kept alive
        for image downloads.

        This is idempotent - calling close() multiple times is safe.
        """
        if self._closed:
            return

        if self._download_context and "ydl" in self._download_context:
            try:
                self._download_context["ydl"].close()
            except Exception:
                pass  # Ignore errors during cleanup
            self._download_context = None

        self._closed = True

    def __enter__(self) -> VideoInfo:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager and close resources."""
        self.close()

    def __del__(self) -> None:
        """Destructor - warn if resources were not explicitly closed."""
        if self._download_context is not None and not self._closed:
            logger.warning(
                f"VideoInfo(id={self.id}) was garbage collected without close() - "
                "potential resource leak. Call close() or use 'with' statement."
            )
            self.close()

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
