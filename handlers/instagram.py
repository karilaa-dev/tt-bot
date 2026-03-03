import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from data.config import locale
from data.db_service import add_video
from data.loader import bot
from media_types.http_session import _download_url
from media_types.image_processing import (
    IMAGE_CONVERSION_AVAILABLE,
    _NATIVE_EXTENSIONS,
    convert_image_to_png,
    detect_image_format,
    ensure_native_format,
    get_image_executor,
)
from media_types.storage import (
    STORAGE_CHANNEL_ID,
    _build_storage_caption,
    upload_photo_to_storage,
)
from media_types.ui import result_caption

from instagram_api import InstagramClient, InstagramMediaInfo

logger = logging.getLogger(__name__)


async def handle_instagram_link(
    message: Message,
    instagram_url: str,
    lang: str,
    file_mode: bool,
    group_chat: bool,
) -> None:
    client = InstagramClient()
    media_info = await client.get_media(instagram_url)

    if media_info.is_video:
        await bot.send_chat_action(
            chat_id=message.chat.id, action="upload_video"
        )
        await _send_instagram_video(message, media_info, lang, file_mode)
    else:
        await bot.send_chat_action(
            chat_id=message.chat.id, action="upload_photo"
        )
        image_limit = 10 if group_chat else None
        await _send_instagram_images(
            message, media_info, lang, file_mode, image_limit
        )

    is_images = not media_info.is_video
    try:
        await add_video(message.chat.id, instagram_url, is_images)
        logger.info(
            f"Instagram Download: CHAT {message.chat.id} - URL {instagram_url}"
        )
    except Exception as e:
        logger.error(f"Can't write into database: {e}")


async def _send_instagram_video(
    message: Message,
    media_info: InstagramMediaInfo,
    lang: str,
    file_mode: bool,
) -> None:
    video_url = media_info.video_url
    if not video_url:
        raise ValueError("No video URL in media info")

    logger.debug(f"Instagram video URL: {video_url}")
    logger.debug(f"Instagram thumbnail URL: {media_info.thumbnail_url}")

    # Download video and thumbnail concurrently
    thumb_coro = _download_url(media_info.thumbnail_url) if media_info.thumbnail_url else None
    if thumb_coro:
        video_bytes, thumb_bytes = await asyncio.gather(
            _download_url(video_url), thumb_coro
        )
    else:
        video_bytes = await _download_url(video_url)
        thumb_bytes = None

    logger.debug(
        f"Instagram video download result: "
        f"video={len(video_bytes) if video_bytes else 'None'} bytes, "
        f"thumb={len(thumb_bytes) if thumb_bytes else 'None'} bytes"
    )

    if not video_bytes:
        raise ConnectionError("Failed to download video")

    thumb = None
    if thumb_bytes:
        thumb = BufferedInputFile(thumb_bytes, "thumb.jpg")

    caption = result_caption(lang, media_info.link)

    if file_mode:
        await bot.send_document(
            chat_id=message.chat.id,
            document=BufferedInputFile(video_bytes, "instagram_video.mp4"),
            thumbnail=thumb,
            caption=caption,
            reply_to_message_id=message.message_id,
            disable_content_type_detection=True,
        )
    else:
        await bot.send_video(
            chat_id=message.chat.id,
            video=BufferedInputFile(video_bytes, "instagram_video.mp4"),
            thumbnail=thumb,
            caption=caption,
            reply_to_message_id=message.message_id,
            supports_streaming=True,
        )


async def _send_instagram_images(
    message: Message,
    media_info: InstagramMediaInfo,
    lang: str,
    file_mode: bool,
    image_limit: int | None,
) -> None:
    # Collect all media URLs (images and videos in carousels)
    media_items = media_info.media
    if image_limit:
        media_items = media_items[:image_limit]

    # Download all media in parallel
    download_tasks = [_download_url(item.url) for item in media_items]
    all_bytes = await asyncio.gather(*download_tasks)

    # Filter out failed downloads, keeping track of which items succeeded
    items_with_bytes = [
        (item, data)
        for item, data in zip(media_items, all_bytes)
        if data is not None
    ]

    if not items_with_bytes:
        raise ConnectionError("Failed to download any media")

    # Convert HEIC/non-native images to PNG in parallel
    if not file_mode and IMAGE_CONVERSION_AVAILABLE:
        loop = asyncio.get_running_loop()
        executor = get_image_executor()

        async def maybe_convert(item, img_bytes):
            if item.type != "image":
                return img_bytes
            ext = detect_image_format(img_bytes)
            if ext not in _NATIVE_EXTENSIONS:
                try:
                    return await loop.run_in_executor(
                        executor, convert_image_to_png, img_bytes
                    )
                except Exception as e:
                    logger.error(f"Failed to convert image: {e}")
            return img_bytes

        convert_tasks = [
            maybe_convert(item, data) for item, data in items_with_bytes
        ]
        converted = await asyncio.gather(*convert_tasks)
        items_with_bytes = [
            (item, data)
            for (item, _), data in zip(items_with_bytes, converted)
        ]

    # Split into batches of 10
    batches = [
        items_with_bytes[i : i + 10]
        for i in range(0, len(items_with_bytes), 10)
    ]

    final = None
    for batch in batches:
        media_group = []
        for idx, (item, img_bytes) in enumerate(batch):
            if item.type == "video":
                filename = f"instagram_video_{idx + 1}.mp4"
            else:
                ext = detect_image_format(img_bytes)
                filename = f"instagram_{idx + 1}{ext}"

            buffered = BufferedInputFile(img_bytes, filename)

            if file_mode or item.type == "video":
                media_group.append(
                    InputMediaDocument(
                        media=buffered,
                        disable_content_type_detection=True,
                    )
                )
            else:
                media_group.append(InputMediaPhoto(media=buffered))

        if media_group:
            try:
                final = await message.reply_media_group(
                    media_group, disable_notification=True
                )
            except TelegramBadRequest as e:
                logger.error(f"Failed to send media group: {e}")

    if final and len(final) > 0:
        await final[0].reply(
            result_caption(lang, media_info.link, bool(image_limit)),
            disable_web_page_preview=True,
        )


async def send_instagram_inline(
    inline_message_id: str,
    instagram_url: str,
    lang: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    """Download Instagram media and send it as an inline message edit."""
    client = InstagramClient()
    media_info = await client.get_media(instagram_url)

    if media_info.is_video:
        await _send_instagram_inline_video(
            inline_message_id, media_info, lang, user_id, username, full_name
        )
    else:
        await _send_instagram_inline_image(
            inline_message_id, media_info, lang, user_id, username, full_name
        )


async def _send_instagram_inline_video(
    inline_message_id: str,
    media_info: InstagramMediaInfo,
    lang: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    video_url = media_info.video_url
    if not video_url:
        raise ValueError("No video URL in media info")

    logger.debug(f"Instagram inline video URL: {video_url}")
    logger.debug(f"Instagram inline thumbnail URL: {media_info.thumbnail_url}")

    # Download video and thumbnail concurrently
    thumb_coro = (
        _download_url(media_info.thumbnail_url) if media_info.thumbnail_url else None
    )
    if thumb_coro:
        video_bytes, thumb_bytes = await asyncio.gather(
            _download_url(video_url), thumb_coro
        )
    else:
        video_bytes = await _download_url(video_url)
        thumb_bytes = None

    logger.debug(
        f"Instagram inline video download result: "
        f"video={len(video_bytes) if video_bytes else 'None'} bytes, "
        f"thumb={len(thumb_bytes) if thumb_bytes else 'None'} bytes"
    )

    if not video_bytes:
        raise ConnectionError("Failed to download video")

    await bot.edit_message_text(
        inline_message_id=inline_message_id,
        text=locale[lang]["sending_inline_video"],
    )

    # Upload to storage channel to get file_id (required for inline edits)
    thumb_file = BufferedInputFile(thumb_bytes, "thumb.jpg") if thumb_bytes else None

    storage_msg = await bot.send_video(
        chat_id=STORAGE_CHANNEL_ID,
        video=BufferedInputFile(video_bytes, "instagram_video.mp4"),
        caption=_build_storage_caption(
            media_info.link, user_id, username, full_name
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
        caption=result_caption(lang, media_info.link),
        supports_streaming=True,
    )
    await bot.edit_message_media(
        inline_message_id=inline_message_id, media=video_media
    )


async def _send_instagram_inline_image(
    inline_message_id: str,
    media_info: InstagramMediaInfo,
    lang: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> None:
    from handlers.inline_slideshow import register_slideshow

    image_urls = media_info.image_urls
    if not image_urls:
        raise ValueError("No image items in media info")

    _, image_data = await asyncio.gather(
        bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=locale[lang]["sending_inline_image"],
        ),
        _download_url(image_urls[0]),
    )
    if not image_data:
        raise ConnectionError("Failed to download image")

    image_data = await ensure_native_format(image_data)

    caption = result_caption(lang, media_info.link)
    if len(image_urls) > 1:
        file_id, keyboard = await register_slideshow(
            inline_message_id, image_urls, image_data, lang, media_info.link,
            user_id, username, full_name,
        )
    else:
        file_id = await upload_photo_to_storage(
            image_data, media_info.link, user_id, username, full_name
        )
        keyboard = None
        if not file_id:
            raise ValueError(
                "Failed to upload photo to storage. "
                "Make sure STORAGE_CHANNEL_ID is configured in .env"
            )

    photo_media = InputMediaPhoto(media=file_id, caption=caption)
    await bot.edit_message_media(
        inline_message_id=inline_message_id,
        media=photo_media,
        reply_markup=keyboard,
    )
