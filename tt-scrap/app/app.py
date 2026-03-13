"""FastAPI REST API server for media scraping."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import settings
from .exceptions import (
    ContentDeletedError,
    ContentPrivateError,
    ContentTooLongError,
    ExtractionError,
    InvalidLinkError,
    NetworkError,
    RateLimitError,
    RegionBlockedError,
    ScraperError,
    UnsupportedServiceError,
)
from .models import ErrorResponse
from .proxy_manager import ProxyManager
from .registry import ServiceRegistry
from .routes import router
from .services import create_tiktok_service

logger = logging.getLogger(__name__)

_ERROR_STATUS_MAP: dict[type[ScraperError], int] = {
    ContentDeletedError: 404,
    ContentPrivateError: 403,
    InvalidLinkError: 400,
    UnsupportedServiceError: 400,
    ContentTooLongError: 413,
    RateLimitError: 429,
    NetworkError: 502,
    RegionBlockedError: 451,
    ExtractionError: 500,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    proxy_manager = (
        ProxyManager.initialize(
            settings.proxy_file,
            include_host=settings.proxy_include_host,
        )
        if settings.proxy_file
        else None
    )

    registry = ServiceRegistry()
    tiktok = create_tiktok_service(proxy_manager=proxy_manager)
    registry.register(tiktok)
    app.include_router(tiktok.router)

    app.state.registry = registry

    logger.info("Scraper API started")
    yield

    for service in registry.get_all():
        if service.shutdown:
            await service.shutdown()

    logger.info("Scraper API stopped")


app = FastAPI(
    title="Media Scraper API",
    version="0.2.0",
    lifespan=lifespan,
)


@app.exception_handler(ScraperError)
async def scraper_error_handler(request, exc: ScraperError):
    status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=str(exc),
            error_type=type(exc).__name__,
        ).model_dump(),
    )


app.include_router(router)
