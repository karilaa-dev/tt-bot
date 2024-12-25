import asyncio
import logging

from data.config import config
from data.loader import scheduler, sqlite, bot, dp
from handlers.admin import admin_router
from handlers.advert import advert_router
from handlers.get_music import music_router
from handlers.get_video import video_router
from handlers.lang import lang_router
from handlers.stats import stats_router
from handlers.user import user_router
from misc.stats import stats_log
from misc.utils import backup_dp

if config["logs"]["stats_chat"] != "0":
    scheduler.add_job(stats_log)
    scheduler.add_job(stats_log, "interval", seconds=3600)
scheduler.add_job(backup_dp, "cron", args=[config["logs"]["backup_logs"]], hour=0)


async def main() -> None:
    scheduler.start()
    dp.include_routers(
        user_router,
        lang_router,
        admin_router,
        advert_router,
        stats_router,
        video_router,
        music_router
    )
    bot_info = await bot.get_me()
    logging.info(f'{bot_info.full_name} [@{bot_info.username}, id:{bot_info.id}]')
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    sqlite.close()
