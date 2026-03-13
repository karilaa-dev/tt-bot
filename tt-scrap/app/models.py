"""Pydantic API response models for the scraper REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MusicResponse(BaseModel):
    url: str
    title: str
    author: str
    duration: int
    cover: str


class VideoResponse(BaseModel):
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
    id: int
    resolved_url: str
    data: dict[str, Any]


class MusicDetailResponse(BaseModel):
    id: int
    title: str
    author: str
    duration: int
    cover: str
    url: str


class RawMusicResponse(BaseModel):
    id: int
    data: dict[str, Any]


class HealthResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    error: str
    error_type: str
