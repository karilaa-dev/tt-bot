from asyncio import sleep

import aiohttp
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

from data.config import locale


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


async def send_video_result(user_msg, video_info, lang, file_mode, link):
    video_id = video_info['id']
    async with aiohttp.ClientSession() as client:
        if file_mode is False:
            async with client.get(video_info['cover'], allow_redirects=True) as cover_request:
                cover_bytes = await cover_request.read()
        async with client.get(video_info['data'], allow_redirects=True) as video_request:
            video_bytes = BufferedInputFile(await video_request.read(), f'{video_id}.mp4')
    if file_mode is False:
        await user_msg.reply_video(video=video_bytes, caption=result_caption(lang, link),
                                   thumb=BufferedInputFile(cover_bytes, 'thumb.jpg'),
                                   height=video_info['height'],
                                   width=video_info['width'],
                                   duration=video_info['duration'] // 1000, reply_markup=music_button(video_id, lang))
    else:
        await user_msg.reply_document(document=video_bytes, caption=result_caption(lang, link),
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


async def send_image_result(user_msg, video_info, lang, file_mode, link, image_limit, cheat_mode=False):
    video_id = video_info['id']
    image_number = 0
    if image_limit:
        images = [video_info['data'][:image_limit]]
        sleep_time = 0
    else:
        images = [video_info['data'][x:x + 10] for x in range(0, len(video_info['data']), 10)]
        image_pages = len(images)
        match image_pages:
            case 1:     sleep_time = 0
            case 2:     sleep_time = 1
            case 3 | 4: sleep_time = 2
            case _:     sleep_time = 3
    client = aiohttp.ClientSession()
    last_part = len(images) - 1
    for num, part in enumerate(images):
        media_group = MediaGroupBuilder()
        for image in part:
            image_number += 1
            async with client.get(image) as image_request:
                image_bytes = await image_request.read()
            data = BufferedInputFile(image_bytes, f'{video_id}-{image_number}.jpg')
            if file_mode:
                media_group.add_document(media=data)
            else:
                media_group.add_photo(media=data)
        if num < last_part:
            await sleep(sleep_time)
            await user_msg.reply_media_group(media_group.build(), disable_notification=True)
        else:
            final = await user_msg.reply_media_group(media_group.build(), disable_notification=True)
    await final[0].reply(result_caption(lang, link, bool(image_limit)), reply_markup=music_button(video_id, lang),
                         disable_web_page_preview=True)
    await client.close()
