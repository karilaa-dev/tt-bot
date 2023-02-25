import logging

from aiogram import types

from data.config import locale
from data.loader import dp, cursor, sqlite
from misc.tiktok_api import ttapi
from misc.utils import lang_func, tCurrent, start_manager
from misc.video_types import send_video_result, send_image_result

api = ttapi()


@dp.message_handler()
async def send_tiktok_video(message: types.Message):
    chat_id = message.chat.id
    lang = lang_func(chat_id, message['from']['language_code'])
    req = cursor.execute('SELECT EXISTS(SELECT 1 FROM users WHERE id = ?)',
                         (chat_id,)).fetchone()[0]
    if req == 0:
        await start_manager(chat_id, message, lang)
    if message.chat.type == 'private':
        group_chat = False
    else:
        group_chat = True
    try:
        video_id, link = await api.get_id(message.text, chat_id)
        if video_id is None:
            if not group_chat:
                await message.reply(locale[lang]['link_error'])
            return
        temp_msg = await message.answer('⏳', disable_notification=group_chat)
        video_info = await api.video(video_id)
        if video_info in [None, False]:
            if not group_chat:
                if video_info is False:
                    await message.reply(locale[lang]['link_error'])
                else:
                    await message.reply(locale[lang]['error'])
            return
        file_mode = bool(
            cursor.execute("SELECT file_mode FROM users WHERE id = ?",
                           (chat_id,)).fetchone()[0])
        if video_info['type'] == 'images':
            if group_chat:
                image_limit = 10
            else:
                image_limit = None
            await send_image_result(temp_msg, video_info, lang, file_mode, link, image_limit)
        else:
            await send_video_result(temp_msg, video_info, lang, file_mode, link)
        try:
            cursor.execute(f'INSERT INTO videos VALUES (?,?,?,?)',
                           (message.chat.id, tCurrent(), link, video_info['type'] == 'images'))
            sqlite.commit()
            logging.info(f'{message.chat.id}: {link}')
        except:
            logging.error('Cant write into database')

    except:
        await temp_msg.delete()
        if not group_chat:
            await message.reply(locale[lang]['error'])
        return
