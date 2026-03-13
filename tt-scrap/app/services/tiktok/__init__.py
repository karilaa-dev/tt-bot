"""TikTok scraper service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...registry import ServiceEntry
from .client import TikTokClient
from .routes import router, set_client

if TYPE_CHECKING:
    from ...proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


async def _shutdown_tiktok() -> None:
    await TikTokClient.close_http_client()
    TikTokClient.shutdown_executor()


def create_tiktok_service(
    proxy_manager: "ProxyManager | None" = None,
) -> ServiceEntry:
    client = TikTokClient(proxy_manager=proxy_manager)
    set_client(client)

    logger.info("TikTok scraper service initialized")

    return ServiceEntry(
        name="tiktok",
        client=client,
        router=router,
        shutdown=_shutdown_tiktok,
    )
