import asyncio
import logging
import re

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
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

from data.config import config, locale
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings
from tiktok_api import TikTokClient, TikTokError, ProxyManager
from instagram_api import INSTAGRAM_URL_REGEX, InstagramClient, InstagramError
from misc.queue_manager import QueueManager
from media_types import get_error_message
from media_types.http_session import _download_url, download_thumbnail
from media_types.image_processing import ensure_native_format
from media_types.storage import (
    STORAGE_CHANNEL_ID,
    _build_storage_caption,
    upload_photo_to_storage,
    upload_video_to_storage,
)
from media_types.ui import result_caption, stats_keyboard
from handlers.inline_slideshow import register_slideshow

inline_router = Router(name=__name__)

INLINE_RETRY_CALLBACK_PREFIX = "ir"
_INLINE_RETRY_DELAY = 0.5
_INLINE_RETRY_ATTEMPTS = 3
_INLINE_TOTAL_ATTEMPTS = _INLINE_RETRY_ATTEMPTS + 1
_TIKTOK_URL_REGEX = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+", re.IGNORECASE)
_retrying_inline_messages: set[str] = set()

# Minimal button required to enable inline_message_id for editing
_loading_button = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏳", callback_data="loading")]]
)


def _normalize_inline_link(raw_link: str, is_instagram: bool) -> str:
    """Extract the source URL from the inline query text."""
    match = (
        INSTAGRAM_URL_REGEX.search(raw_link)
        if is_instagram
        else _TIKTOK_URL_REGEX.search(raw_link)
    )
    link = match.group(0) if match else raw_link.strip()
    return link.rstrip(".,)")


def _compress_inline_link(source_link: str, is_instagram: bool) -> str:
    """Compress a source URL enough to fit in Telegram callback_data."""
    link = _normalize_inline_link(source_link, is_instagram)
    if not is_instagram:
        link = link.split("?")[0]
        link = re.sub(r"@[\w.]+", "@", link)
    link = re.sub(r"^https?://", "", link)
    return link


def _expand_inline_link(compressed: str) -> str:
    return f"https://{compressed}"


def _build_inline_retry_keyboard(
    lang: str, source_link: str, is_instagram: bool
) -> InlineKeyboardMarkup | None:
    source = "ig" if is_instagram else "tt"
    callback_data = (
        f"{INLINE_RETRY_CALLBACK_PREFIX}:"
        f"{source}:{_compress_inline_link(source_link, is_instagram)}"
    )
    if len(callback_data.encode("utf-8")) > 64:
        logging.warning("Inline retry callback_data is too long: %s", callback_data)
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=locale[lang]["try_again_button"],
                    callback_data=callback_data,
                )
            ]
        ]
    )


def _with_retry_text(
    base_text: str, lang: str, retry_attempt: int, max_retries: int
) -> str:
    return (
        base_text.rstrip()
        + "\n"
        + locale[lang]["inline_retry_attempt"].format(retry_attempt, max_retries)
    )


async def _safe_edit_inline_text(
    inline_message_id: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        logging.debug("Failed to update inline message text")
    except Exception as err:
        logging.warning(f"Unexpected error updating inline message: {err}")


async def _edit_inline_retry_status(
    inline_message_id: str,
    base_text: str,
    lang: str,
    retry_attempt: int,
    max_retries: int,
) -> None:
    await _safe_edit_inline_text(
        inline_message_id,
        _with_retry_text(base_text, lang, retry_attempt, max_retries),
        reply_markup=_loading_button,
    )


async def _edit_inline_error(
    inline_message_id: str,
    text: str,
    lang: str,
    source_link: str,
    is_instagram: bool,
) -> None:
    await _safe_edit_inline_text(
        inline_message_id,
        text,
        reply_markup=_build_inline_retry_keyboard(lang, source_link, is_instagram),
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


@inline_router.callback_query(
    lambda cb: cb.data and cb.data.startswith(f"{INLINE_RETRY_CALLBACK_PREFIX}:")
)
async def handle_inline_retry_callback(callback: CallbackQuery) -> None:
    inline_message_id = callback.inline_message_id
    if not inline_message_id:
        await callback.answer()
        return

    if inline_message_id in _retrying_inline_messages:
        await callback.answer("Retrying...")
        return

    parts = callback.data.split(":", 2) if callback.data else []
    if len(parts) != 3 or parts[1] not in {"ig", "tt"}:
        await callback.answer("Invalid retry data.", show_alert=True)
        return

    is_instagram = parts[1] == "ig"
    source_link = _expand_inline_link(parts[2])

    user_id = callback.from_user.id
    username = callback.from_user.username
    full_name = callback.from_user.full_name
    settings = await get_user_settings(user_id)
    if settings:
        lang, file_mode = settings
    else:
        lang = await lang_func(user_id, callback.from_user.language_code, True)
        file_mode = False

    _retrying_inline_messages.add(inline_message_id)
    try:
        await _safe_edit_inline_text(
            inline_message_id,
            locale[lang]["inline_download_video_text"],
            reply_markup=_loading_button,
        )
        await callback.answer()
        await _handle_inline_download(
            inline_message_id,
            source_link,
            lang,
            file_mode,
            user_id,
            username,
            full_name,
            is_instagram=is_instagram,
        )
    finally:
        _retrying_inline_messages.discard(inline_message_id)


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
    source_link = _normalize_inline_link(video_link, is_instagram)

    try:
        async with queue.info_queue(user_id, bypass_user_limit=True) as acquired:
            if not acquired:
                await _edit_inline_error(
                    message_id,
                    locale[lang]["error"],
                    lang,
                    source_link,
                    is_instagram,
                )
                return

            if is_instagram:
                client = InstagramClient()

                async def on_instagram_info_retry(
                    retry_attempt: int, max_retries: int
                ) -> None:
                    await _edit_inline_retry_status(
                        message_id,
                        locale[lang]["inline_download_video_text"],
                        lang,
                        retry_attempt,
                        max_retries,
                    )

                media_info = await client.get_media(
                    source_link,
                    max_attempts=_INLINE_TOTAL_ATTEMPTS,
                    retry_delay=_INLINE_RETRY_DELAY,
                    on_retry=on_instagram_info_retry,
                )
            else:
                api = TikTokClient(
                    proxy_manager=ProxyManager.get_instance(),
                    data_only_proxy=config["proxy"]["data_only"],
                )

                async def on_tiktok_retry(
                    retry_attempt: int, max_retries: int
                ) -> None:
                    await _edit_inline_retry_status(
                        message_id,
                        locale[lang]["inline_download_video_text"],
                        lang,
                        retry_attempt,
                        max_retries,
                    )

                video_info = await api.video_with_retry(
                    source_link,
                    max_attempts=_INLINE_TOTAL_ATTEMPTS,
                    request_timeout=60.0,
                    base_delay=_INLINE_RETRY_DELAY,
                    on_retry=on_tiktok_retry,
                )

        if is_instagram:
            is_video = media_info.is_video
        else:
            is_video = video_info.is_video
        is_images = not is_video

        if is_instagram or not is_video:
            await _safe_edit_inline_text(
                message_id,
                locale[lang][
                    "downloading_inline_video"
                    if is_video
                    else "downloading_inline_image"
                ],
                reply_markup=_loading_button,
            )

        if is_instagram:

            if not media_info.is_video:
                # Instagram images/carousel
                image_urls = media_info.image_urls
                if not image_urls:
                    await _edit_inline_error(
                        message_id,
                        locale[lang]["error"],
                        lang,
                        source_link,
                        is_instagram,
                    )
                    return

                async def on_image_download_retry(
                    retry_attempt: int, max_retries: int
                ) -> None:
                    await _edit_inline_retry_status(
                        message_id,
                        locale[lang]["downloading_inline_image"],
                        lang,
                        retry_attempt,
                        max_retries,
                    )

                image_data = await _download_url(
                    image_urls[0],
                    max_retries=_INLINE_TOTAL_ATTEMPTS,
                    retry_delay=_INLINE_RETRY_DELAY,
                    on_retry=on_image_download_retry,
                )
                if not image_data:
                    raise ConnectionError("Failed to download image")

                image_data = await ensure_native_format(image_data)

                caption = result_caption(lang, source_link)
                if len(image_urls) > 1:
                    file_id, keyboard = await register_slideshow(
                        message_id, image_urls, image_data, lang, source_link,
                        user_id, username, full_name,
                    )
                else:
                    file_id = await upload_photo_to_storage(
                        image_data, source_link, user_id, username, full_name
                    )
                    keyboard = None
                    if not file_id:
                        raise ValueError(
                            "Failed to upload photo to storage. "
                            "Make sure STORAGE_CHANNEL_ID is configured in .env"
                        )

                await _safe_edit_inline_text(
                    message_id,
                    locale[lang]["sending_inline_image"],
                    reply_markup=_loading_button,
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

                async def on_video_download_retry(
                    retry_attempt: int, max_retries: int
                ) -> None:
                    await _edit_inline_retry_status(
                        message_id,
                        locale[lang]["downloading_inline_video"],
                        lang,
                        retry_attempt,
                        max_retries,
                    )

                download_coros = [
                    _download_url(
                        video_url,
                        max_retries=_INLINE_TOTAL_ATTEMPTS,
                        retry_delay=_INLINE_RETRY_DELAY,
                        on_retry=on_video_download_retry,
                    )
                ]
                if media_info.thumbnail_url:
                    download_coros.append(
                        _download_url(
                            media_info.thumbnail_url,
                            max_retries=_INLINE_TOTAL_ATTEMPTS,
                            retry_delay=_INLINE_RETRY_DELAY,
                        )
                    )

                results = await asyncio.gather(*download_coros)
                video_bytes = results[0]
                thumb_bytes = results[1] if len(results) > 1 else None

                if not video_bytes:
                    raise ConnectionError("Failed to download video")

                await _safe_edit_inline_text(
                    message_id,
                    locale[lang]["sending_inline_video"],
                    reply_markup=_loading_button,
                )

                thumb_file = (
                    BufferedInputFile(thumb_bytes, "thumb.jpg")
                    if thumb_bytes else None
                )
                if not STORAGE_CHANNEL_ID:
                    raise ValueError(
                        "Failed to upload video to storage. "
                        "Make sure STORAGE_CHANNEL_ID is configured in .env"
                    )

                storage_msg = await bot.send_video(
                    chat_id=STORAGE_CHANNEL_ID,
                    video=BufferedInputFile(video_bytes, "instagram_video.mp4"),
                    caption=_build_storage_caption(
                        source_link, user_id, username, full_name
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
                    caption=result_caption(lang, source_link),
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
                        await _edit_inline_error(
                            message_id,
                            locale[lang]["error"],
                            lang,
                            source_link,
                            is_instagram,
                        )
                        return

                    image_data = await api.download_image(image_urls[0], video_info)
                    if not image_data:
                        raise ConnectionError("Failed to download image")

                    image_data = await ensure_native_format(image_data)

                    caption = result_caption(lang, source_link)
                    if len(image_urls) > 1:
                        file_id, keyboard = await register_slideshow(
                            message_id, image_urls, image_data, lang, source_link,
                            user_id, username, full_name,
                            client=api, video_info=video_info,
                            likes=video_info.likes, views=video_info.views,
                        )
                    else:
                        file_id = await upload_photo_to_storage(
                            image_data, source_link, user_id, username, full_name
                        )
                        keyboard = stats_keyboard(video_info.likes, video_info.views)
                        if not file_id:
                            raise ValueError(
                                "Failed to upload photo to storage. "
                                "Make sure STORAGE_CHANNEL_ID is configured in .env"
                            )

                    await _safe_edit_inline_text(
                        message_id,
                        locale[lang]["sending_inline_image"],
                        reply_markup=_loading_button,
                    )

                    photo_media = InputMediaPhoto(media=file_id, caption=caption)
                    await bot.edit_message_media(
                        inline_message_id=message_id,
                        media=photo_media,
                        reply_markup=keyboard,
                    )
                else:
                    await _safe_edit_inline_text(
                        message_id,
                        locale[lang]["sending_inline_video"],
                        reply_markup=_loading_button,
                    )

                    video_bytes = video_info.video_bytes
                    if not video_bytes:
                        raise ValueError("Video data must be bytes for inline messages")

                    thumbnail = None
                    if video_info.duration and video_info.duration > 30:
                        thumbnail = await download_thumbnail(
                            video_info.cover, video_info.id
                        )

                    file_id = await upload_video_to_storage(
                        video_bytes,
                        video_info,
                        user_id,
                        username,
                        full_name,
                        thumbnail=thumbnail,
                    )

                    if not file_id:
                        raise ValueError(
                            "Failed to upload video to storage. "
                            "Make sure STORAGE_CHANNEL_ID is configured in .env"
                        )

                    video_media = InputMediaVideo(
                        media=file_id,
                        caption=result_caption(lang, source_link),
                        width=video_info.width,
                        height=video_info.height,
                        duration=video_info.duration,
                        supports_streaming=True,
                    )
                    await bot.edit_message_media(
                        inline_message_id=message_id,
                        media=video_media,
                        reply_markup=stats_keyboard(video_info.likes, video_info.views),
                    )
            finally:
                video_info.close()

        try:
            await add_video(user_id, source_link, is_images, False, True)
            logging.info(
                f"Inline Download: {user_id} - "
                f"{'IMAGES' if is_images else 'VIDEO'} {source_link}"
            )
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)

    except (TikTokError, InstagramError) as e:
        logging.error(
            f"{'Instagram' if is_instagram else 'TikTok'} error for inline "
            f"{source_link}: {e}"
        )
        await _edit_inline_error(
            message_id,
            get_error_message(e, lang),
            lang,
            source_link,
            is_instagram,
        )
    except Exception as e:
        logging.error(e)
        await _edit_inline_error(
            message_id,
            locale[lang]["error"],
            lang,
            source_link,
            is_instagram,
        )
