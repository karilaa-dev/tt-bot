import logging
from datetime import datetime
from sys import exc_info
from time import time
from traceback import format_exception

from aiogram.filters import Filter
from aiogram.types import FSInputFile, Message, BufferedInputFile

from data.config import locale, admin_ids, second_ids, config
from data.db_service import get_user, create_user, get_user_ids
from data.loader import bot


def tCurrent():
    return int(time())


async def lang_func(usrid: int, usrlang: str, no_request=False) -> str:
    try:
        if not no_request:
            try:
                user = await get_user(usrid)
                if user:
                    return user.lang
            except Exception:
                pass

        if usrlang not in locale['langs']:
            return 'en'
        return usrlang
    except Exception:
        return 'en'


async def backup_dp(chat_id: int):
    try:
        await bot.send_document(chat_id=chat_id, document=FSInputFile(config["bot"]["db_name"]),
                                caption=f'#Backup💾\n<code>{datetime.utcnow()}</code>')
    except:
        pass


async def start_manager(chat_id, message: Message, lang):
    text = message.text.split(' ')
    if len(text) > 1:
        args = text[1].lower()
    else:
        args = ''
    if args == '':
        args = None
    await create_user(chat_id, lang, args)
    username = ''
    if message.chat.username is not None:
        username = f'@{message.chat.username}\n'
    text = f'<b><a href="tg://user?id={chat_id}">{message.chat.full_name}</a></b>' \
           f'\n{username}<code>{chat_id}</code>\n<i>{args or ""}</i>'
    await bot.send_message(chat_id=config["logs"]["join_logs"], text=text)
    username = username.replace('\n', ' ')
    logging.info(f'New User: {message.chat.full_name} {username}{chat_id} {args or ""}')
    if chat_id > 0:
        start_text = locale[lang]['start'] + locale[lang]['group_info']
    else:
        start_text = locale[lang]['start']
    await message.answer(start_text, disable_web_page_preview=True)
    await message.answer(locale[lang]['lang_start'])


class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.from_user.id in admin_ids:
            return True
        else:
            return False


class IsSecondAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.from_user.id in second_ids:
            return True
        else:
            return False


def error_catch(e):
    error_type, error_instance, tb = exc_info()
    tb_str = format_exception(error_type, error_instance, tb)
    error_message = "".join(tb_str)
    return error_message

async def get_users_file(only_positive: bool = False):
    users = await get_user_ids(only_positive=only_positive)
    users_result = '\n'.join(str(user_id) for user_id in users)
    users_result = users_result.encode('utf-8')
    request_file = BufferedInputFile(users_result, filename='users.txt')
    return request_file
