import asyncio
import logging

from data.config import config
from data.loader import scheduler, bot, dp, setup_db
from handlers.admin import admin_router
from handlers.advert import advert_router
from handlers.get_music import music_router
from handlers.get_video import video_router
from handlers.lang import lang_router
from handlers.stats import stats_router
from handlers.user import user_router
from misc.stats import update_overall_stats, update_daily_stats
from misc.utils import backup_dp

if config["logs"]["stats_chat"] != "0":
    # Split message mode - run both immediately
    scheduler.add_job(update_overall_stats, misfire_grace_time=None)
    scheduler.add_job(update_daily_stats, misfire_grace_time=None)
    # Schedule separate updates
    scheduler.add_job(update_overall_stats, "interval", hours=1, id='stats_overall', misfire_grace_time=None)
    scheduler.add_job(update_daily_stats, "interval", minutes=5, id='stats_daily', misfire_grace_time=None)


async def main() -> None:
    await setup_db()
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
