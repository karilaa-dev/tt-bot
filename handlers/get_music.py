import logging

from aiogram import types
from aiogram.types import InputFile

from data.config import locale
from data.loader import dp, bot, cursor, sqlite
from misc.tiktok_api import ttapi
from misc.utils import lang_func, tCurrent

api = ttapi()


@dp.callback_query_handler(
    lambda call: call.data.startswith('id') or call.data.startswith('music'),
    state='*')
async def send_tiktok_sound(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type == 'private':
        group_chat = False
    else:
        group_chat = True
    chat_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    lang = lang_func(from_id, callback_query['from']['language_code'],
                     group_chat)
    msg = await bot.send_message(chat_id, '⏳', disable_notification=group_chat)
    try:
        video_id = callback_query.data.lstrip('id/')
        playAddr = await api.music(int(video_id))
        if playAddr is None:
            raise
        caption = locale[lang]['result_song'].format(locale[lang]['bot_tag'],
                                                     playAddr['cover'])
        audio = InputFile.from_url(url=playAddr['url'])
        cover = InputFile.from_url(url=playAddr['cover'])
        await bot.send_chat_action(chat_id, 'upload_document')
        await bot.send_audio(chat_id, audio, reply_to_message_id=msg_id,
                             caption=caption, title=playAddr['title'],
                             performer=playAddr['author'],
                             duration=playAddr['duration'], thumb=cover,
                             disable_notification=group_chat)
        await callback_query.message.edit_reply_markup()
        await msg.delete()
        try:
            cursor.execute('INSERT INTO music VALUES (?,?,?)',
                           (callback_query["from"]["id"], tCurrent(), video_id))
            sqlite.commit()
            logging.info(f'{callback_query["from"]["id"]}: Music - {video_id}')
        except:
            logging.error('Cant write into database')
    except:
        try:
            await msg.delete()
        except:
            pass
        if not group_chat:
            await bot.send_message(chat_id, locale[lang]['error'])
    return await callback_query.answer()
