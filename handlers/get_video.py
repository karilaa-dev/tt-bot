import logging

from aiogram import types
from aiogram.types import InputFile, InputMediaVideo, InputMediaDocument, InlineKeyboardMarkup, InlineKeyboardButton

from data.config import locale
from data.loader import dp, api, cursor, sqlite
from misc.utils import lang_func, tCurrent


@dp.message_handler()
async def send_ttdown(message: types.Message):
    if message.chat.type == 'private':
        group_chat = False
    else:
        group_chat = True
    try:
        lang = lang_func(message['from']['id'],
                         message['from']['language_code'],
                         group_chat)
        await message.answer_chat_action('upload_video')
        video_id, link = await api.get_id(message.text)
        if video_id is None:
            if not group_chat == 'private':
                await message.answer(locale[lang]['link_error'])
            return
        playAddr = await api.video(video_id)
        if playAddr is None:
            if not group_chat:
                await message.answer(locale[lang]['error'])
            return

        cover = InputFile.from_url(url=playAddr['cover'])
        temp_msg = await message.answer_photo(cover, locale[lang]['downloading'], disable_notification=group_chat)
        result_caption = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
        music_button = InlineKeyboardMarkup().add(
            InlineKeyboardButton(locale[lang]['get_sound'], callback_data=f'id/{playAddr["id"]}'))

        vid = InputFile.from_url(url=playAddr['url'],
                                 filename=f'{video_id}.mp4')
        if not group_chat == 'private':
            file_mode = bool(
                cursor.execute("SELECT file_mode FROM users WHERE id = ?",
                               (message.chat.id,)).fetchone()[0])
        else:
            file_mode = False
        if file_mode is False:
            media = InputMediaVideo(media=vid, caption=result_caption, thumb=cover,
                                    height=playAddr['height'],
                                    width=playAddr['width'],
                                    duration=playAddr['duration'] // 1000)
        else:
            media = InputMediaDocument(media=vid, caption=result_caption,
                                       disable_content_type_detection=True)
        await temp_msg.edit_media(media=media, reply_markup=music_button)
        try:
            if group_chat:
                log_table_name = 'groups'
            else:
                log_table_name = 'videos'
            cursor.execute(f'INSERT INTO {log_table_name} VALUES (?,?,?)',
                           (message["chat"]["id"], tCurrent(), link))
            sqlite.commit()
            logging.info(f'{message["from"]["id"]}: {link}')
        except:
            logging.error('Cant write into database')

    except:
        try:
            await temp_msg.delete()
        except:
            pass
        if not group_chat:
            await message.answer(locale[lang]['error'])
        return
