import json
from data import db_service as db
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from data.loader import bot
from data.config import adsgram_block_id
import aiohttp


async def show_ad(chat_id: int, lang: str):
    try:
        text_html, click_url, button_name, image_url = await request_ad(chat_id, lang)
    except Exception as e:
        await db.reset_ad_counter(chat_id)
        raise e
    button = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_name, url=click_url)]])
    await bot.send_photo(chat_id=chat_id, photo=image_url, caption=text_html, reply_markup=button, protect_content=True)
    await db.reset_ad_counter(chat_id)

async def request_ad(chat_id: int, lang: str):
    # return "Ad <b>example</b>", "https://t.me/ttgrab_bot", "Click me", "https://i.imgur.com/EMzXscT.jpeg"
    url = f"https://api.adsgram.ai/advbot?tgid={chat_id}&blockid={adsgram_block_id}&language={lang}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if await response.text() == 'No available advertisement at the moment, try again later!':
                raise Exception('Banner not available')
            json_data = await response.json()

    json_data = json.loads(json_data)
    return json_data['text_html'], json_data['click_url'], json_data['button_name'], json_data['image_url']