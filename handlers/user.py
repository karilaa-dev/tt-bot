from aiogram import F
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from data.config import locale
from data.db_service import get_user, update_user_mode
from data.loader import bot
from misc.utils import lang_func, start_manager

user_router = Router(name=__name__)


@user_router.message(CommandStart(), F.chat.type == 'private')
async def send_start(message: Message) -> None:
    chat_id = message.chat.id
    lang = await lang_func(chat_id, message.from_user.language_code)
    user = await get_user(chat_id)
    if not user:
        await start_manager(chat_id, message, lang)
    else:
        if chat_id > 0:
            start_text = locale[lang]['start'] + locale[lang]['group_info']
        else:
            start_text = locale[lang]['start']
        await message.answer(start_text, disable_web_page_preview=True)
        await message.answer(locale[lang]['lang_start'])


@user_router.message(Command('mode'))
async def change_mode(message: Message):
    chat_id = message.chat.id
    lang = await lang_func(chat_id, message.from_user.language_code)
    if message.chat.type != 'private':
        user_status = await bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        if user_status.status not in ['creator', 'administrator']:
            return await message.answer(locale[lang]['not_admin'])
    user = await get_user(chat_id)
    if not user:
        file_mode = False
    else:
        file_mode = user.file_mode
    await update_user_mode(chat_id, not file_mode)
    if file_mode:
        text = locale[lang]['file_mode_off']
    else:
        text = locale[lang]['file_mode_on']
    await message.answer(text)
