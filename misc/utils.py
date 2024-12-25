import logging
from datetime import datetime
from sys import exc_info
from time import time
from traceback import format_exception

from aiogram.filters import Filter
from aiogram.types import FSInputFile, Message

from data.config import locale, admin_ids, second_ids, config
from data.loader import cursor, sqlite, bot


def tCurrent():
    return int(time())


def lang_func(usrid: int, usrlang: str, no_request=False):
    try:
        if not no_request:
            lang_req = cursor.execute("SELECT lang FROM users WHERE id = ?",
                                      (usrid,)).fetchone()
        else:
            lang_req = None

        if lang_req is not None:
            lang = lang_req[0]
        else:
            if usrlang not in locale['langs']:
                lang = 'en'
            else:
                lang = usrlang

        return lang
    except:
        return 'en'


async def backup_dp(chat_id: int):
    try:
        await bot.send_document(chat_id, FSInputFile(config["bot"]["db_name"]),
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
    cursor.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)',
                   (chat_id, tCurrent(), lang, args, 0))
    sqlite.commit()
    username = ''
    if message.chat.username is not None:
        username = f'@{message.chat.username}\n'
    text = f'<b><a href="tg://user?id={chat_id}">{message.chat.full_name}</a></b>' \
           f'\n{username}<code>{chat_id}</code>\n<i>{args or ""}</i>'
    await bot.send_message(config["logs"]["join_logs"], text)
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
