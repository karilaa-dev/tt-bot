import logging
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.config import bot_token, local_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                    handlers=[
                        # logging.FileHandler("bot.log"),
                        logging.StreamHandler()
                    ])
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
logging.getLogger('apscheduler.scheduler').propagate = False
logging.getLogger('aiogram').setLevel(logging.WARNING)

bot = Bot(token=bot_token, session=local_server, parse_mode=ParseMode.HTML)

dp = Dispatcher(storage=MemoryStorage())

scheduler = AsyncIOScheduler(timezone="Europe/Kiev")

sqlite = sqlite3.connect('sqlite.db')
cursor = sqlite.cursor()
