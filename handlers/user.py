from aiogram import types

from aiogram import types

from data.config import locale
from data.loader import dp, bot, cursor, sqlite
from misc.utils import lang_func, start_manager


@dp.message_handler(commands=['start'], chat_type='private', state='*')
async def send_start(message: types.Message):
    chat_id = message.chat.id
    req = cursor.execute('SELECT EXISTS(SELECT 1 FROM users WHERE id = ?)',
                         (chat_id,)).fetchone()[0]
    lang = lang_func(chat_id, message['from']['language_code'])
    if req == 0:
        await start_manager(chat_id, message, lang)
    else:
        if chat_id > 0:
            start_text = locale[lang]['start'] + locale[lang]['group_info']
        else:
            start_text = locale[lang]['start']
        await message.answer(start_text)
        await message.answer(locale[lang]['lang_start'])


@dp.message_handler(commands=['mode'], state='*')
async def change_mode(message: types.message):
    chat_id = message.chat.id
    lang = lang_func(chat_id, message['from']['language_code'])
    if message.chat.type != 'private':
        user_status = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if user_status.status not in ['creator', 'administrator']:
            return await message.answer(locale[lang]['not_admin'])
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
