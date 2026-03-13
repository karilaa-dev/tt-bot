"""Base client protocol for scraper services."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseClient(Protocol):
    """Protocol that all service clients must implement.

    extract_video_info must return a dict with keys:
      - video_data: dict (raw service-specific data)
      - video_id: str (content identifier)
      - resolved_url: str (canonical URL)

    extract_music_info must return None if not supported, or a dict with keys:
      - video_data: dict (raw data)
      - music_data: dict (music-specific data)
      - video_id: int
    """

    async def extract_video_info(self, url: str) -> dict[str, Any]: ...

    async def extract_music_info(self, video_id: int) -> dict[str, Any] | None: ...
