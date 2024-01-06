from asyncio import sleep

from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder
from httpx import AsyncClient, AsyncHTTPTransport

from data.config import locale


def music_button(video_id, lang):
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]['get_sound'], callback_data=f'id/{video_id}')
    return keyb.as_markup()


def result_caption(lang, link, group_warning=None):
    result = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
    if group_warning:
        result += locale[lang]['group_warning']
    return result


async def send_video_result(user_msg, video_info, lang, file_mode, link):
    video_id = video_info['id']
    async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
        if file_mode is False:
            cover_request = await client.get(video_info['cover'], follow_redirects=True)
        video_request = await client.get(video_info['data'], follow_redirects=True)
    vid = BufferedInputFile(video_request.content, f'{video_id}.mp4')
    if file_mode is False:
        await user_msg.reply_video(video=vid, caption=result_caption(lang, link),
                                    thumb=BufferedInputFile(cover_request.content, 'thumb.jpg'),
                                    height=video_info['height'],
                                    width=video_info['width'],
                                    duration=video_info['duration'] // 1000, reply_markup=music_button(video_id, lang))
    else:
        await user_msg.reply_document(document=vid, caption=result_caption(lang, link),
                                       disable_content_type_detection=True, reply_markup=music_button(video_id, lang))


async def send_music_result(query_msg, music_info, lang, group_chat):
    video_id = music_info['id']
    async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
        audio_request = await client.get(music_info['data'], follow_redirects=True)
        cover_request = await client.get(music_info['cover'], follow_redirects=True)
    audio = BufferedInputFile(audio_request.content, f'{video_id}.mp3')
    cover = BufferedInputFile(cover_request.content, f'{video_id}.jpg')
    caption = locale[lang]['result_song'].format(locale[lang]['bot_tag'],
                                                 music_info['cover'])
    # Send music
    await query_msg.reply_audio(audio,
                         caption=caption, title=music_info['title'],
                         performer=music_info['author'],
                         duration=music_info['duration'], thumbnail=cover,
                         disable_notification=group_chat)


async def send_image_result(user_msg, video_info, lang, file_mode, link, image_limit):
    video_id = video_info['id']
    image_number = 0
    if image_limit:
        images = [video_info['data'][:image_limit]]
    else:
        images = [video_info['data'][x:x + 10] for x in range(0, len(video_info['data']), 10)]
    client = AsyncClient(transport=AsyncHTTPTransport(retries=2))
    last_part = len(images) - 1
    for num, part in enumerate(images):
        media_group = MediaGroupBuilder()
        for image in part:
            image_number += 1
            req = await client.get(image)
            data = BufferedInputFile(req.content, f'{video_id}-{image_number}.jpg')
            if file_mode:
                media_group.add_document(media=data)
            else:
                media_group.add_photo(media=data)
        if num < last_part:
            await sleep(2)
            await user_msg.reply_media_group(media_group.build(), disable_notification=True)
        else:
            final = await user_msg.reply_media_group(media_group.build(), disable_notification=True)
    await final[0].reply(result_caption(lang, link, bool(image_limit)), reply_markup=music_button(video_id, lang),
                         disable_web_page_preview=True)
    await client.aclose()
