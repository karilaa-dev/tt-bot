import logging

from aiogram import types, F, Router
from aiogram.types import BufferedInputFile
from httpx import AsyncClient, AsyncHTTPTransport

from data.config import locale
from data.loader import dp, bot, cursor, sqlite
from misc.tiktok_api import ttapi
from misc.utils import lang_func, tCurrent

music_router = Router(name=__name__)

api = ttapi()


@dp.callback_query(F.data.startswith('id'))
async def send_tiktok_sound(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type == 'private':
        group_chat = False
    else:
        group_chat = True
    chat_id = callback_query.message.chat.id
    msg_id = callback_query.message.message_id
    lang = lang_func(chat_id, callback_query.from_user.language_code)
    temp_msg = await bot.send_message(chat_id, '⏳', disable_notification=group_chat)
    # try:
    video_id = callback_query.data.lstrip('id/')
    playAddr = await api.music(int(video_id))
    if playAddr in [None, False]:
        raise
    caption = locale[lang]['result_song'].format(locale[lang]['bot_tag'],
                                                 playAddr['cover'])
    async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
        audio_request = await client.get(playAddr['data'], follow_redirects=True)
        cover_request = await client.get(playAddr['cover'], follow_redirects=True)
    audio = BufferedInputFile(audio_request.content, f'{video_id}.mp3')
    cover = BufferedInputFile(cover_request.content, 'thumb.jpg')
    await bot.send_chat_action(chat_id, 'upload_document')
    await bot.send_audio(chat_id, audio, reply_to_message_id=msg_id,
                         message_thread_id=callback_query.message.message_thread_id,
                         caption=caption, title=playAddr['title'],
                         performer=playAddr['author'],
                         duration=playAddr['duration'], thumbnail=cover,
                         disable_notification=group_chat)
    await callback_query.message.edit_reply_markup()
    await temp_msg.delete()
    # try:
    cursor.execute('INSERT INTO music VALUES (?,?,?)',
                   (chat_id, tCurrent(), video_id))
    sqlite.commit()
    logging.info(f'{chat_id}: Music - {video_id}')
    # except:
    # logging.error('Cant write into database')
# except:
#     try:
#         await temp_msg.delete()
#     except:
#         pass
#     if not group_chat:
#         await bot.send_message(chat_id, locale[lang]['error'], reply_to_message_id=msg_id)
# return await callback_query.answer()
