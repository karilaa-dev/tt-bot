import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.config import config
from data.database import init_db, initialize_database_components

_NOISY_LOGGER_LEVELS = {
    "aiogram": logging.WARNING,
    "apscheduler": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "aiohttp": logging.WARNING,
    "aiohttp.access": logging.WARNING,
    "asyncio": logging.WARNING,
}

logging.basicConfig(
    level=config["logging"]["log_level"],
    format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
    handlers=[
        # logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ],
)
for logger_name, logger_level in _NOISY_LOGGER_LEVELS.items():
    logging.getLogger(logger_name).setLevel(logger_level)
logging.getLogger("apscheduler.scheduler").propagate = False

local_server = AiohttpSession(
    api=TelegramAPIServer.from_base(config["bot"]["tg_server"])
)
bot = Bot(
    token=config["bot"]["token"],
    session=local_server,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())

scheduler = AsyncIOScheduler(
    timezone="America/Los_Angeles", job_defaults={"coalesce": True}
)


async def setup_db(db_url: str):
    initialize_database_components(db_url)
    await init_db()
