import logging

from aiogram import types

from data.loader import dp, bot, cursor, sqlite
from data.config import logs, locale
from misc.utils import lang_func, tCurrent


@dp.message_handler(commands=['start'], chat_type=types.ChatType.PRIVATE)
async def send_start(message: types.Message):
    chat_id = message.chat.id
    req = cursor.execute('SELECT EXISTS(SELECT 1 FROM users WHERE id = ?)',
                         (chat_id,)).fetchone()[0]
    lang = lang_func(chat_id, message['from']['language_code'], False)
    if req == 0:
        args = message.get_args().lower()
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
        await bot.send_message(logs, text)
        username = username.replace('\n', ' ')
        logging.info(
            f'{message.chat.full_name} {username}{chat_id} {args or ""}')
    await message.answer(locale[lang]['start'])
    await message.answer(locale[lang]['lang_start'])


@dp.message_handler(commands=['mode'], chat_type=types.ChatType.PRIVATE, state='*')
async def change_mode(message: types.message):
    chat_id = message.chat.id
    lang = lang_func(chat_id, message['from']['language_code'], False)
    try:
        file_mode = bool(
            cursor.execute("SELECT file_mode FROM users WHERE id = ?",
                           (chat_id,)).fetchone()[0])
    except:
        file_mode = False
    cursor.execute("UPDATE users SET file_mode = ? WHERE id = ?",
                   (not file_mode, chat_id,))
    sqlite.commit()
    if file_mode is True:
        text = locale[lang]['file_mode_off']
    else:
        text = locale[lang]['file_mode_on']
    await message.answer(text)
