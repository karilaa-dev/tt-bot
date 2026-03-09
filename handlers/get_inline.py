import asyncio
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineQuery,
    ChosenInlineResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InputMediaPhoto,
    InputMediaVideo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultsButton,
)

from data.config import locale
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings
from tiktok_api import TikTokClient, TikTokError, ProxyManager
from instagram_api import INSTAGRAM_URL_REGEX, InstagramClient, InstagramError
from misc.queue_manager import QueueManager
from media_types import send_video_result, get_error_message
from media_types.http_session import _download_url
from media_types.image_processing import ensure_native_format
from media_types.storage import STORAGE_CHANNEL_ID, _build_storage_caption, upload_photo_to_storage
from media_types.ui import result_caption, stats_keyboard
from handlers.inline_slideshow import register_slideshow

inline_router = Router(name=__name__)

# Minimal button required to enable inline_message_id for editing
_loading_button = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏳", callback_data="loading")]]
)


@inline_router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    """Handle inline queries and return example results"""
    api = TikTokClient(proxy_manager=ProxyManager.get_instance())
    query_text = inline_query.query.strip()
    user_id = inline_query.from_user.id
    lang = await lang_func(user_id, inline_query.from_user.language_code)
    user_info = await get_user(user_id)
    results = []

    if user_info is None:
        start_bot_button = InlineQueryResultsButton(
            text=locale[lang]["inline_start_bot"], start_parameter="inline"
        )
        return await inline_query.answer(
            results, cache_time=0, button=start_bot_button, is_personal=True
        )

    if len(query_text) < 12:
        return await inline_query.answer(results, cache_time=0)

    video_link, is_mobile = await api.regex_check(query_text)
    if video_link is not None:
        results.append(
            InlineQueryResultArticle(
                id="tt_download",
                title=locale[lang]["inline_download_video"],
                description=locale[lang]["inline_download_video_description"],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]["inline_download_video_text"]
                ),
                thumbnail_url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/tiktok-light.png",
                reply_markup=_loading_button,
            )
        )
    elif INSTAGRAM_URL_REGEX.search(query_text):
        results.append(
            InlineQueryResultArticle(
                id="ig_download",
                title=locale[lang]["inline_download_instagram"],
                description=locale[lang]["inline_download_instagram_description"],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]["inline_download_video_text"]
                ),
                thumbnail_url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/instagram.png",
                reply_markup=_loading_button,
            )
        )
    else:
        results.append(
            InlineQueryResultArticle(
                id="wrong_link",
                title=locale[lang]["inline_wrong_link_title"],
                description=locale[lang]["inline_wrong_link_description"],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]["inline_wrong_link"], parse_mode="HTML"
                ),
                thumbnail_url="https://em-content.zobj.net/source/apple/419/cross-mark_274c.png",
            )
        )

    await inline_query.answer(results, cache_time=0)


@inline_router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult):
    """Handle when user selects an inline result"""
    user_id = chosen_result.from_user.id
    username = chosen_result.from_user.username
    full_name = chosen_result.from_user.full_name
    message_id = chosen_result.inline_message_id
    video_link = chosen_result.query
    settings = await get_user_settings(user_id)
    if not settings:
        return
    lang, file_mode = settings

    is_instagram = chosen_result.result_id == "ig_download"

    await _handle_inline_download(
        message_id, video_link, lang, file_mode,
        user_id, username, full_name, is_instagram=is_instagram,
    )


async def _handle_inline_download(
    message_id: str,
    video_link: str,
    lang: str,
    file_mode: bool,
    user_id: int,
    username: str | None,
    full_name: str | None,
    *,
    is_instagram: bool = False,
) -> None:
    queue = QueueManager.get_instance()

    try:
        async with queue.info_queue(user_id, bypass_user_limit=True) as acquired:
            if not acquired:
                await bot.edit_message_text(
                    inline_message_id=message_id, text=locale[lang]["error"]
                )
                return

            if is_instagram:
                client = InstagramClient()
                media_info = await client.get_media(video_link)
            else:
                api = TikTokClient(proxy_manager=ProxyManager.get_instance())
                video_info = await api.video(video_link)

        if is_instagram:
            is_video = media_info.is_video
        else:
            is_video = video_info.is_video
        is_images = not is_video

        # For TikTok video, the download already happened inside api.video(),
        # so the initial message already covers the downloading phase.
        if is_instagram or not is_video:
            await bot.edit_message_text(
                inline_message_id=message_id,
                text=locale[lang]["downloading_inline_video" if is_video else "downloading_inline_image"],
            )

        if is_instagram:

            if not media_info.is_video:
                # Instagram images/carousel
                image_urls = media_info.image_urls
                if not image_urls:
                    await bot.edit_message_text(
                        inline_message_id=message_id, text=locale[lang]["error"]
                    )
                    return

                image_data = await _download_url(image_urls[0])
                if not image_data:
                    raise ConnectionError("Failed to download image")

                image_data = await ensure_native_format(image_data)

                caption = result_caption(lang, video_link)
                if len(image_urls) > 1:
                    file_id, keyboard = await register_slideshow(
                        message_id, image_urls, image_data, lang, video_link,
                        user_id, username, full_name,
                    )
                else:
                    file_id = await upload_photo_to_storage(
                        image_data, video_link, user_id, username, full_name
                    )
                    keyboard = None
                    if not file_id:
                        raise ValueError(
                            "Failed to upload photo to storage. "
                            "Make sure STORAGE_CHANNEL_ID is configured in .env"
                        )

                await bot.edit_message_text(
                    inline_message_id=message_id,
                    text=locale[lang]["sending_inline_image"],
                )

                photo_media = InputMediaPhoto(media=file_id, caption=caption)
                await bot.edit_message_media(
                    inline_message_id=message_id,
                    media=photo_media,
                    reply_markup=keyboard,
                )
            else:
                # Instagram video
                video_url = media_info.video_url
                if not video_url:
                    raise ValueError("No video URL in media info")

                download_coros = [_download_url(video_url)]
                if media_info.thumbnail_url:
                    download_coros.append(_download_url(media_info.thumbnail_url))

                results = await asyncio.gather(*download_coros)
                video_bytes = results[0]
                thumb_bytes = results[1] if len(results) > 1 else None

                if not video_bytes:
                    raise ConnectionError("Failed to download video")

                await bot.edit_message_text(
                    inline_message_id=message_id,
                    text=locale[lang]["sending_inline_video"],
                )

                thumb_file = (
                    BufferedInputFile(thumb_bytes, "thumb.jpg")
                    if thumb_bytes else None
                )
                storage_msg = await bot.send_video(
                    chat_id=STORAGE_CHANNEL_ID,
                    video=BufferedInputFile(video_bytes, "instagram_video.mp4"),
                    caption=_build_storage_caption(
                        video_link, user_id, username, full_name
                    ),
                    parse_mode="HTML",
                    disable_notification=True,
                    thumbnail=thumb_file,
                    supports_streaming=True,
                )

                file_id = storage_msg.video.file_id if storage_msg.video else None
                if not file_id:
                    raise ValueError(
                        "Failed to upload video to storage. "
                        "Make sure STORAGE_CHANNEL_ID is configured in .env"
                    )

                video_media = InputMediaVideo(
                    media=file_id,
                    caption=result_caption(lang, video_link),
                    supports_streaming=True,
                )
                await bot.edit_message_media(
                    inline_message_id=message_id, media=video_media
                )
        else:
            try:
                if video_info.is_slideshow:
                    image_urls = video_info.image_urls

                    if not image_urls:
                        await bot.edit_message_text(
                            inline_message_id=message_id, text=locale[lang]["error"]
                        )
                        return

                    image_data = await api.download_image(image_urls[0], video_info)
                    if not image_data:
                        raise ConnectionError("Failed to download image")

                    image_data = await ensure_native_format(image_data)

                    caption = result_caption(lang, video_link)
                    if len(image_urls) > 1:
                        file_id, keyboard = await register_slideshow(
                            message_id, image_urls, image_data, lang, video_link,
                            user_id, username, full_name,
                            client=api, video_info=video_info,
                            likes=video_info.likes, views=video_info.views,
                        )
                    else:
                        file_id = await upload_photo_to_storage(
                            image_data, video_link, user_id, username, full_name
                        )
                        keyboard = stats_keyboard(video_info.likes, video_info.views)
                        if not file_id:
                            raise ValueError(
                                "Failed to upload photo to storage. "
                                "Make sure STORAGE_CHANNEL_ID is configured in .env"
                            )

                    await bot.edit_message_text(
                        inline_message_id=message_id,
                        text=locale[lang]["sending_inline_image"],
                    )

                    photo_media = InputMediaPhoto(media=file_id, caption=caption)
                    await bot.edit_message_media(
                        inline_message_id=message_id,
                        media=photo_media,
                        reply_markup=keyboard,
                    )
                else:
                    await bot.edit_message_text(
                        inline_message_id=message_id, text=locale[lang]["sending_inline_video"]
                    )

                    await send_video_result(
                        message_id,
                        video_info,
                        lang,
                        file_mode,
                        inline_message=True,
                        user_id=user_id,
                        username=username,
                        full_name=full_name,
                    )
            finally:
                video_info.close()

        try:
            await add_video(user_id, video_link, is_images, False, True)
            logging.info(f"Inline Download: {user_id} - {'IMAGES' if is_images else 'VIDEO'} {video_link}")
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)

    except (TikTokError, InstagramError) as e:
        logging.error(f"{'Instagram' if is_instagram else 'TikTok'} error for inline {video_link}: {e}")
        try:
            await bot.edit_message_text(
                inline_message_id=message_id, text=get_error_message(e, lang)
            )
        except TelegramBadRequest:
            logging.debug("Failed to update inline error message")
        except Exception as err:
            logging.warning(f"Unexpected error updating inline message: {err}")
    except Exception as e:
        logging.error(e)
        try:
            await bot.edit_message_text(
                inline_message_id=message_id, text=locale[lang]["error"]
            )
        except TelegramBadRequest:
            logging.debug("Failed to update inline error message")
        except Exception as err:
            logging.warning(f"Unexpected error updating inline message: {err}")
