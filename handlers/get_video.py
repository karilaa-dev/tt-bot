import logging
import re

from aiogram import types
from aiogram.types import InputFile, InputMediaVideo, InputMediaDocument, InlineKeyboardMarkup, InlineKeyboardButton

from data.loader import dp, api, cursor, sqlite, aSession
from data.config import locale
from misc.utils import lang_func


web_regex = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
mus_regex = re.compile(r'https?://www.tiktok.com/music/[^\s]+')
mob_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
red_regex = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')


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
        try:
            if web_regex.match(message.text) is not None:
                await message.answer_chat_action('upload_video')
                link = web_regex.findall(message.text)[0]
                vid_id = red_regex.findall(message.text)[0]
                playAddr = await api.video(vid_id)
                status = True
                error_link = False
                if playAddr == 'errorlink':
                    status = False
                    error_link = True
                elif playAddr in ['error', 'connerror']:
                    status = False
            elif mob_regex.match(message.text) is not None:
                await message.answer_chat_action('upload_video')
                link = mob_regex.findall(message.text)[0]
                session = await aSession.get_session()
                req = await session.request("get", link)
                result_caption = str(req.url)
                vid_id = red_regex.findall(result_caption)[0]
                playAddr = await api.video(vid_id)
                status = True
                error_link = False
                if playAddr == 'errorlink':
                    status = False
                    error_link = True
                elif playAddr in ['error', 'connerror']:
                    status = False
            else:
                if message.chat.type == 'private':
                    await message.answer(locale[lang]['link_error'])
                return
        except:
            error_link = True
            status = False

        if status is True:
            cover = InputFile.from_url(url=playAddr['cover'])
            temp_msg = await message.answer_photo(cover, locale[lang]['downloading'], disable_notification=group_chat)
            result_caption = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
            music_button = InlineKeyboardMarkup().add(
                InlineKeyboardButton(locale[lang]['get_sound'], callback_data=f'id/{playAddr["id"]}'))

            vid = InputFile.from_url(url=playAddr['url'],
                                     filename=f'{vid_id}.mp4')
            if message.chat.type == 'private':
                try:
                    file_mode = bool(
                        cursor.execute(
                            "SELECT file_mode FROM users WHERE id = ?",
                            [message.chat.id]).fetchone()[0])
                except:
                    file_mode = False
            else:
                file_mode = False
            if file_mode is False:
                media = InputMediaVideo(media=vid, caption=result_caption, thumb=cover,
                                        height=playAddr['height'],
                                        width=playAddr['width'],
                                        duration=playAddr['duration'] // 1000)
                await temp_msg.edit_media(media=media, reply_markup=music_button)

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
                logging.error('Неудалось записать в бд')
        else:
            if message.chat.type == 'private':
                if error_link is True:
                    error_text = locale[lang]['link_error']
                else:
                    error_text = locale[lang]['error']
                await message.answer(error_text)
            return


    except:
        try:
            await temp_msg.delete()
        except:
            pass
        if message.chat.type == 'private':
            await message.answer(locale[lang]['error'])
        return