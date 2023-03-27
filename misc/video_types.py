from asyncio import sleep
from io import BytesIO

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaDocument, \
    InputMediaPhoto
from httpx import AsyncClient, AsyncHTTPTransport

from data.config import locale


def music_button(video_id, lang):
    keyb = InlineKeyboardMarkup()
    keyb.add(InlineKeyboardButton(locale[lang]['get_sound'], callback_data=f'id/{video_id}'))
    return keyb


def result_caption(lang, link, group_warning=None):
    result = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
    if group_warning:
        result += locale[lang]['group_warning']
    return result


async def send_video_result(temp_msg, video_info, lang, file_mode, link):
    video_id = video_info['id']
    async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
        cover_request = await client.get(video_info['cover'], follow_redirects=True)
        video_request = await client.get(video_info['data'], follow_redirects=True)
    vid = BytesIO(video_request.content)
    vid.name = f'{video_id}.mp4'
    if file_mode is False:
        await temp_msg.answer_video(video=vid, caption=result_caption(lang, link), thumb=BytesIO(cover_request.content),
                                    height=video_info['height'],
                                    width=video_info['width'],
                                    duration=video_info['duration'] // 1000, reply_markup=music_button(video_id, lang))
    else:
        await temp_msg.answer_document(document=vid, caption=result_caption(lang, link),
                                       disable_content_type_detection=True, reply_markup=music_button(video_id, lang))
    await temp_msg.delete()


async def send_image_result(temp_msg, video_info, lang, file_mode, link, image_limit):
    video_id = video_info['id']
    image_number = 0
    if image_limit:
        images = [video_info['data'][:image_limit]]
    else:
        images = [video_info['data'][x:x + 10] for x in range(0, len(video_info['data']), 10)]
    client = AsyncClient(transport=AsyncHTTPTransport(retries=2))
    last_part = len(images) - 1
    for num, part in enumerate(images):
        media = []
        for image in part:
            image_number += 1
            req = await client.get(image)
            data = BytesIO(req.content)
            if file_mode:
                data.name = f'{video_id}-{image_number}.jpg'
                media.append(InputMediaDocument(data))
            else:
                media.append(InputMediaPhoto(data))
        if num < last_part:
            await sleep(2)
            await temp_msg.answer_media_group(media, disable_notification=True)
        else:
            final = await temp_msg.answer_media_group(media, disable_notification=True)
    await final[0].reply(result_caption(lang, link, bool(image_limit)), reply_markup=music_button(video_id, lang),
                         disable_web_page_preview=True)
    await temp_msg.delete()
    await client.aclose()