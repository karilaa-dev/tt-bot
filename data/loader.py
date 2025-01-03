import logging
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from data.config import config

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

scheduler = AsyncIOScheduler(timezone="Europe/Kiev")

sqlite = sqlite3.connect(config["bot"]["db_name"])
cursor = sqlite.cursor()
