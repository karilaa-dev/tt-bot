import logging
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.config import bot_token, local_server
from misc.tiktok_api import AsyncSession, ttapi


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                    handlers=[
                        # logging.FileHandler("bot.log"),
                        logging.StreamHandler()
                    ])
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
logging.getLogger('apscheduler.scheduler').propagate = False

bot = Bot(token=bot_token, server=local_server, parse_mode='html')
dp = Dispatcher(bot, storage=MemoryStorage())

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

aSession = AsyncSession()

api = ttapi()
sqlite = sqlite3.connect('sqlite.db')
cursor = sqlite.cursor()
