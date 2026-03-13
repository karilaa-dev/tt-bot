"""FastAPI dependencies for TikTok scrapper API."""

from __future__ import annotations

from fastapi import Request

from .client import TikTokClient


def get_client(request: Request) -> TikTokClient:
    """Get the TikTokClient instance from application state."""
    return request.app.state.client
