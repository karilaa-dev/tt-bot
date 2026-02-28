from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InstagramMediaItem:
    type: str  # "video" or "image"
    url: str
    thumbnail: str | None = None
    quality: str | None = None


@dataclass
class InstagramMediaInfo:
    media: list[InstagramMediaItem] = field(default_factory=list)
    link: str = ""

    @property
    def is_video(self) -> bool:
        return len(self.media) == 1 and self.media[0].type == "video"

    @property
    def is_carousel(self) -> bool:
        return len(self.media) > 1

    @property
    def image_urls(self) -> list[str]:
        return [item.url for item in self.media if item.type == "image"]

    @property
    def video_url(self) -> str | None:
        for item in self.media:
            if item.type == "video":
                return item.url
        return None

    @property
    def thumbnail_url(self) -> str | None:
        for item in self.media:
            if item.thumbnail:
                return item.thumbnail
        return None
