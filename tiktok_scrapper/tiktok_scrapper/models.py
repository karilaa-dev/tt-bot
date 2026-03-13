"""Pydantic API response models for TikTok scrapper REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MusicResponse(BaseModel):
    """Music metadata returned as part of a video response."""

    url: str
    title: str
    author: str
    duration: int
    cover: str


class VideoResponse(BaseModel):
    """Filtered video/slideshow response."""

    type: str  # "video" or "images"
    id: int
    video_url: str | None = None
    image_urls: list[str] = []
    cover: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    likes: int | None = None
    views: int | None = None
    link: str
    music: MusicResponse | None = None


class RawVideoResponse(BaseModel):
    """Raw TikTok API response (full yt-dlp extraction data)."""

    id: int
    resolved_url: str
    data: dict[str, Any]


class MusicDetailResponse(BaseModel):
    """Filtered music response for the /music endpoint."""

    id: int
    title: str
    author: str
    duration: int
    cover: str
    url: str


class RawMusicResponse(BaseModel):
    """Raw music data from TikTok API."""

    id: int
    data: dict[str, Any]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"


class ErrorResponse(BaseModel):
    """Error response body."""

    error: str
    error_type: str
