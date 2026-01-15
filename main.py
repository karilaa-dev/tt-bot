import asyncio
import logging

from data.config import config
from data.loader import scheduler, bot, dp, setup_db
from handlers.admin import admin_router
from handlers.advert import advert_router
from handlers.get_music import music_router
from handlers.get_video import video_router
from handlers.lang import lang_router
from handlers.user import user_router
from handlers.get_inline import inline_router
from misc.video_types import close_http_session
from stats.misc import update_overall_stats, update_daily_stats
from tiktok_api import ProxyManager, TikTokClient


async def main() -> None:
    await setup_db(config["bot"]["db_url"])

    # Initialize proxy manager if configured
    if config["proxy"]["proxy_file"]:
        ProxyManager.initialize(
            proxy_file=config["proxy"]["proxy_file"],
            include_host=config["proxy"]["include_host"],
        )
        logging.info("Proxy manager initialized")

    scheduler.start()
    dp.include_routers(
        user_router,
        lang_router,
        admin_router,
        advert_router,
        video_router,
        music_router,
        inline_router,
    )
    bot_info = await bot.get_me()
    logging.info(f"{bot_info.full_name} [@{bot_info.username}, id:{bot_info.id}]")

    try:
        await dp.start_polling(bot)
    finally:
        # Cleanup shared resources on shutdown
        logging.info("Shutting down: cleaning up TikTokClient resources...")
        await TikTokClient.close_curl_session()  # curl_cffi session for media downloads
        await TikTokClient.close_connector()  # aiohttp connector for URL resolution
        TikTokClient.shutdown_executor()
        await close_http_session()  # aiohttp session for thumbnail/cover downloads
        logging.info("TikTokClient resources cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
