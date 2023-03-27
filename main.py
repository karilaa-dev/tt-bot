from aiogram import executor, Dispatcher

from data.config import logs
from data.loader import scheduler, sqlite
from handlers import dp
from misc.stats import stats_log
from misc.utils import backup_dp


async def on_startup(dp: Dispatcher):
    scheduler.add_job(stats_log)
    scheduler.add_job(stats_log, "interval", seconds=300)
    scheduler.add_job(backup_dp, "cron", args=[logs], hour=0)


async def on_shutdown(dp: Dispatcher):
    sqlite.close()


if __name__ == "__main__":
    scheduler.start()
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
