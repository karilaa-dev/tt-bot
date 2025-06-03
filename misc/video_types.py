from asyncio import sleep

import aiohttp
from aiogram.types import BufferedInputFile, InputMediaDocument, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale, config

download_link = config["api"]["api_link"] + '/api/download'
download_params = {'prefix': 'false', 'with_watermark': 'false'}


def music_button(video_id, lang):
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]['get_sound'], callback_data=f'id/{video_id}')
    return keyb.as_markup()


def image_ask_button(video_id, lang):
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]['get_last_10'], callback_data=f'images/last10/{video_id}')
    keyb.button(text=locale[lang]['get_all'], callback_data=f'images/all/{video_id}')
    keyb.adjust(1, 1)
    return keyb.as_markup()


def result_caption(lang, link, group_warning=None):
    result = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
    if group_warning:
        result += locale[lang]['group_warning']
    return result


async def send_video_result(user_msg, video_info, lang, file_mode, alt_mode=False):
    video_id = video_info['id']
    async with aiohttp.ClientSession() as client:
        if file_mode is False:
            async with client.get(video_info['cover'], allow_redirects=True) as cover_request:
                cover_bytes = await cover_request.read()
        if alt_mode:
            url = video_info['data']
            params = {}
            video_duration = video_info['duration'] // 1000
        else:
            url = download_link
            download_params['url'] = video_info['link']
            params = download_params
            video_duration = video_info['duration']
        async with client.get(url, allow_redirects=True, params=params) as video_request:
            video_bytes = BufferedInputFile(await video_request.read(), f'{video_id}.mp4')
    if file_mode is False:
        await user_msg.reply_video(video=video_bytes, caption=result_caption(lang, video_info['link']),
                                   thumb=BufferedInputFile(cover_bytes, 'thumb.jpg'),
                                   height=video_info['height'],
                                   width=video_info['width'],
                                   duration=video_duration, reply_markup=music_button(video_id, lang))
    else:
        await user_msg.reply_document(document=video_bytes, caption=result_caption(lang, video_info['link']),
                                      disable_content_type_detection=True, reply_markup=music_button(video_id, lang))


async def send_music_result(query_msg, music_info, lang, group_chat):
    video_id = music_info['id']
    async with aiohttp.ClientSession() as client:
        async with client.get(music_info['data'], allow_redirects=True) as audio_request:
            audio_bytes = await audio_request.read()
        async with client.get(music_info['cover'], allow_redirects=True) as cover_request:
            cover_bytes = await cover_request.read()
    audio = BufferedInputFile(audio_bytes, f'{video_id}.mp3')
    cover = BufferedInputFile(cover_bytes, f'{video_id}.jpg')
    caption = locale[lang]['result_song'].format(locale[lang]['bot_tag'],
                                                 music_info['cover'])
    # Send music
    await query_msg.reply_audio(audio,
                                caption=caption, title=music_info['title'],
                                performer=music_info['author'],
                                duration=music_info['duration'], thumbnail=cover,
                                disable_notification=group_chat)


async def send_image_result(user_msg, video_info, lang, file_mode, image_limit):
    video_id = video_info['id']
    image_number = 0
    if image_limit:
        images = [video_info['data'][:image_limit]]
        sleep_time = 0
    else:
        images = [video_info['data'][x:x + 10] for x in range(0, len(video_info['data']), 10)]
        image_pages = len(images)
        match image_pages:
            case 1:
                sleep_time = 0
            case 2:
                sleep_time = 1
            case 3 | 4:
                sleep_time = 2
            case _:
                sleep_time = 3
    last_part = len(images) - 1
    for num, part in enumerate(images):
        media_group = []
        for image_link in part:
            image_number += 1
            data = await get_image_data(image_link, f'{video_id}_{image_number}.jpg')
            if file_mode:
                media_group.append(InputMediaDocument(media=data))
            else:
                media_group.append(InputMediaPhoto(media=data))
        if num < last_part:
            await sleep(sleep_time)
            await user_msg.reply_media_group(media_group, disable_notification=True)
        else:
            final = await user_msg.reply_media_group(media_group, disable_notification=True)
    await final[0].reply(result_caption(lang, video_info['link'], bool(image_limit)),
                         reply_markup=music_button(video_id, lang),
                         disable_web_page_preview=True)

async def get_image_data(image_link, file_name):
    async with aiohttp.ClientSession() as client:
        async with client.get(image_link, allow_redirects=True) as image_request:
            if image_request.status < 200 or image_request.status >= 300:
                raise aiohttp.ClientResponseError(
                    status=image_request.status,
                    message=f"Failed to fetch image from {image_link}. HTTP status: {image_request.status}"
                )
            image_data = await image_request.read()
    image_bytes = BufferedInputFile(image_data, file_name)
    return image_bytes