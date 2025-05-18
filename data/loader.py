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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                    handlers=[
                        # logging.FileHandler("bot.log"),
                        logging.StreamHandler()
                    ])
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
logging.getLogger('apscheduler.scheduler').propagate = False
logging.getLogger('aiogram').setLevel(logging.WARNING)

local_server = AiohttpSession(api=TelegramAPIServer.from_base(config["bot"]["tg_server"]))
bot = Bot(token=config["bot"]["token"], session=local_server, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher(storage=MemoryStorage())

scheduler = AsyncIOScheduler(timezone="America/Los_Angeles", job_defaults={"coalesce": True})


async def setup_db(db_url: str):
    initialize_database_components(db_url)
    await init_db()
