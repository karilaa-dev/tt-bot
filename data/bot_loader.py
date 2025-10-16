import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from data.config import config
from data.database import init_db, initialize_database_components


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
        handlers=[
            # logging.FileHandler("bot.log"),
            logging.StreamHandler()
        ]
    )
    logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
    logging.getLogger('apscheduler.scheduler').propagate = False
    logging.getLogger('aiogram').setLevel(logging.WARNING)


def create_bot(token: Optional[str] = None) -> Bot:
    """Create and configure a Bot instance."""
    bot_token = token or config["bot"]["token"]
    local_server = AiohttpSession(api=TelegramAPIServer.from_base(config["bot"]["tg_server"]))
    return Bot(
        token=bot_token, 
        session=local_server, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


def create_dispatcher() -> Dispatcher:
    """Create and configure a Dispatcher instance."""
    return Dispatcher(storage=MemoryStorage())


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure an AsyncIOScheduler instance."""
    return AsyncIOScheduler(
        timezone="America/Los_Angeles", 
        job_defaults={"coalesce": True}
    )


async def setup_db(db_url: str):
    """Initialize database components."""
    initialize_database_components(db_url)
    await init_db()


def create_bot_components(token: Optional[str] = None):
    """Create all bot components (bot, dispatcher, scheduler)."""
    setup_logging()
    bot = create_bot(token)
    dp = create_dispatcher()
    scheduler = create_scheduler()
    return bot, dp, scheduler