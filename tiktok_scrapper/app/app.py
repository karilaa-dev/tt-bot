"""FastAPI REST API server for TikTok scrapping."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .client import TikTokClient
from .config import settings
from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
)
from .models import ErrorResponse
from .proxy_manager import ProxyManager
from .routes import router

logger = logging.getLogger(__name__)

_ERROR_STATUS_MAP: dict[type[TikTokError], int] = {
    TikTokDeletedError: 404,
    TikTokPrivateError: 403,
    TikTokInvalidLinkError: 400,
    TikTokVideoTooLongError: 413,
    TikTokRateLimitError: 429,
    TikTokNetworkError: 502,
    TikTokRegionError: 451,
    TikTokExtractionError: 500,
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

    app.state.client = TikTokClient(
        proxy_manager=proxy_manager,
    )

    logger.info("TikTok scrapper API started")
    yield

    await TikTokClient.close_http_client()
    TikTokClient.shutdown_executor()
    logger.info("TikTok scrapper API stopped")


app = FastAPI(
    title="TikTok Scrapper API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(TikTokError)
async def tiktok_error_handler(request, exc: TikTokError):
    status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=str(exc),
            error_type=type(exc).__name__,
        ).model_dump(),
    )


app.include_router(router)
