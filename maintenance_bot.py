import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

from data.config import config

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s",
                    handlers=[logging.StreamHandler()])

# Load locale
locale = {}
locale["langs"] = []
[locale["langs"].append(file.replace(".json", "")) for file in os.listdir("locale")]
for lang in locale["langs"]:
    with open(f"locale/{lang}.json", 'r', encoding='utf-8') as locale_file:
        locale[lang] = json.loads(locale_file.read())

# Setup bot
bot = Bot(token=config["bot"]["token"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# Create dispatcher
dp = Dispatcher()

# Create maintenance router
maintenance_router = Router(name="maintenance")
maintenance_router.message.filter(F.chat.type == "private")


# Helper function to determine user language
async def get_user_language(user_id, language_code):
    # Default to English if language not supported
    if language_code not in locale['langs']:
        return 'en'
    return language_code

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
