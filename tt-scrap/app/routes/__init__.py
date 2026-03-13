"""API route aggregation."""

from fastapi import APIRouter

from .health import router as health_router
from .music import router as music_router
from .video import router as video_router

router = APIRouter()
router.include_router(video_router)
router.include_router(music_router)
router.include_router(health_router)
