import asyncio
import logging

from data.config import config
from stats.loader import scheduler, bot, dp, setup_db
from stats.router import stats_router
from stats.misc import update_overall_stats, update_daily_stats

if config["logs"]["stats_chat"] != "0":
    # Split message mode - run both immediately
    scheduler.add_job(update_overall_stats, misfire_grace_time=None)
    scheduler.add_job(update_daily_stats, misfire_grace_time=None)
    # Schedule separate updates
    scheduler.add_job(update_overall_stats, "interval", hours=1, id='stats_overall', misfire_grace_time=None)
    scheduler.add_job(update_daily_stats, "interval", minutes=5, id='stats_daily', misfire_grace_time=None)


async def main() -> None:
    await setup_db(config['bot']['db_url'])
    scheduler.start()
    dp.include_routers(
        stats_router,
    )
    bot_info = await bot.get_me()
    logging.info(f'{bot_info.full_name} [@{bot_info.username}, id:{bot_info.id}]')
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
