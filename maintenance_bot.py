import asyncio
import json
import logging
import os
from configparser import ConfigParser

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import Message

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                    handlers=[logging.StreamHandler()])

# Load configuration
config = ConfigParser()
config.read("config.ini")

# Load locale
with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json.loads(locale_file.read())

# Setup bot
local_server = AiohttpSession(api=TelegramAPIServer.from_base(config["bot"]["tg_server"]))
bot = Bot(token=config["bot"]["token"], session=local_server, 
          default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# Create dispatcher
dp = Dispatcher()

# Create maintenance router
maintenance_router = Router(name="maintenance")


# Helper function to determine user language
async def get_user_language(user_id, language_code):
    # Default to English if language not supported
    if language_code not in locale['langs']:
        return 'en'
    return language_code


# Handler for /start command
@maintenance_router.message(F.text.startswith("/start"))
async def start_command(message: Message):
    lang = await get_user_language(message.from_user.id, message.from_user.language_code)
    
    # If language doesn't have maintenance message, use English
    if 'maintenance' not in locale[lang]:
        lang = 'en'
    
    await message.answer(locale[lang]['maintenance'])


# Handler for /lang command
@maintenance_router.message(F.text.startswith("/lang"))
async def lang_command(message: Message):
    lang = await get_user_language(message.from_user.id, message.from_user.language_code)
    
    # If language doesn't have maintenance message, use English
    if 'maintenance' not in locale[lang]:
        lang = 'en'
    
    await message.answer(locale[lang]['maintenance'])


# Handler for all other messages
@maintenance_router.message()
async def maintenance_message(message: Message):
    lang = await get_user_language(message.from_user.id, message.from_user.language_code)
    
    # If language doesn't have maintenance message, use English
    if 'maintenance' not in locale[lang]:
        lang = 'en'
    
    await message.answer(locale[lang]['maintenance'])


async def main() -> None:
    # Include maintenance router
    dp.include_router(maintenance_router)
    
    # Start bot
    bot_info = await bot.get_me()
    logging.info(f'MAINTENANCE MODE: {bot_info.full_name} [@{bot_info.username}, id:{bot_info.id}]')
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
