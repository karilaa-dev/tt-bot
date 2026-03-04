import asyncio
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineQuery,
    ChosenInlineResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultsButton,
)

from data.config import locale, config
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings
from tiktok_api import TikTokClient, TikTokError, ProxyManager
from instagram_api import INSTAGRAM_URL_REGEX, InstagramError
from misc.queue_manager import QueueManager
from media_types import send_video_result, get_error_message
from media_types.image_processing import ensure_native_format
from media_types.storage import upload_photo_to_storage
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

    if is_instagram:
        await _handle_instagram_inline(
            message_id, video_link, lang, user_id, username, full_name
        )
    else:
        await _handle_tiktok_inline(
            message_id, video_link, lang, file_mode,
            user_id, username, full_name,
        )


async def _handle_tiktok_inline(
    message_id: str,
    video_link: str,
    lang: str,
    file_mode: bool,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    api = TikTokClient(proxy_manager=ProxyManager.get_instance())
    queue = QueueManager.get_instance()

    try:
        async with queue.info_queue(user_id, bypass_user_limit=True) as acquired:
            if not acquired:
                await bot.edit_message_text(
                    inline_message_id=message_id, text=locale[lang]["error"]
                )
                return

            video_info = await api.video(video_link)

        try:
            if video_info.is_slideshow:
                image_urls = video_info.image_urls

                if not image_urls:
                    await bot.edit_message_text(
                        inline_message_id=message_id, text=locale[lang]["error"]
                    )
                    return

                _, image_data = await asyncio.gather(
                    bot.edit_message_text(
                        inline_message_id=message_id,
                        text=locale[lang]["sending_inline_image"],
                    ),
                    api.download_image(image_urls[0], video_info),
                )
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

                photo_media = InputMediaPhoto(media=file_id, caption=caption)
                await bot.edit_message_media(
                    inline_message_id=message_id,
                    media=photo_media,
                    reply_markup=keyboard,
                )
                is_images = True
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
                is_images = False
        finally:
            video_info.close()

        try:
            await add_video(user_id, video_link, is_images, False, True)
            logging.info(f"Video Download: INLINE {user_id} - {'IMAGES' if is_images else 'VIDEO'} {video_link}")
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)

    except TikTokError as e:
        logging.error(f"TikTok error for inline {video_link}: {e}")
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


async def _handle_instagram_inline(
    message_id: str,
    video_link: str,
    lang: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    from handlers.instagram import send_instagram_inline

    try:
        await send_instagram_inline(
            message_id, video_link, lang, user_id, username, full_name
        )

        try:
            await add_video(user_id, video_link, False, False, True)
            logging.info(
                f"Instagram Download: INLINE {user_id} - URL {video_link}"
            )
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)

    except InstagramError as e:
        logging.error(f"Instagram error for inline {video_link}: {e}")
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
