import asyncio
import logging
from asyncio import sleep

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InputMediaDocument,
    InputMediaPhoto,
)

from data.config import locale
from tiktok_api import (
    TikTokClient,
    TikTokNetworkError,
    VideoInfo,
)

from .http_session import _download_url
from .image_processing import (
    IMAGE_CONVERSION_AVAILABLE,
    _NATIVE_EXTENSIONS,
    convert_image_to_jpeg_optimized,
    detect_image_format,
    get_image_executor,
)
from .ui import result_caption, video_reply_markup

logger = logging.getLogger(__name__)


async def download_images_parallel(
    image_urls: list[str],
    client: TikTokClient,
    video_info: VideoInfo,
) -> list[bytes | BaseException]:
    return await asyncio.gather(
        *[client.download_image(url, video_info) for url in image_urls],
        return_exceptions=True,
    )


async def _download_images_http(image_urls: list[str]) -> list[bytes]:
    """Download images via plain HTTP (for non-TikTok sources)."""
    results = await asyncio.gather(*[_download_url(url) for url in image_urls])
    downloaded = [r for r in results if r is not None]
    if not downloaded:
        raise ConnectionError("Failed to download any images")
    return downloaded


async def send_image_result(
    user_msg,
    video_info: VideoInfo,
    lang: str,
    file_mode: bool,
    image_limit: int | None,
    client: TikTokClient | None = None,
) -> bool:
    """Send slideshow images to the user.

    Downloads all images first, then processes and sends them.
    Returns True if image processing (conversion) was performed.
    """
    video_id = video_info.id
    image_urls = video_info.image_urls
    video_indices = video_info._video_indices

    if image_limit:
        image_urls = image_urls[:image_limit]

    total_images = len(image_urls)
    processing_needed = False
    processing_message = None
    was_processed = False

    is_private_chat = user_msg.chat.type == "private"

    # Download all images with retry
    if client is not None:
        proxy_session = video_info._proxy_session
        if proxy_session:
            try:
                all_image_bytes = await client.download_slideshow_images(
                    video_info, proxy_session
                )
                if image_limit:
                    all_image_bytes = all_image_bytes[:image_limit]
            except TikTokNetworkError as e:
                logger.error(f"Failed to download slideshow images: {e}")
                raise
        else:
            logger.warning("No proxy session available, using legacy download")
            all_image_bytes = await download_images_parallel(
                image_urls, client, video_info
            )
            all_image_bytes = [
                img for img in all_image_bytes if isinstance(img, bytes)
            ]
            if not all_image_bytes:
                logger.error(
                    f"All {len(image_urls)} slideshow images failed in fallback mode"
                )
                raise TikTokNetworkError("Failed to download slideshow images")
    else:
        all_image_bytes = await _download_images_http(image_urls)

    # Split into batches of 10 for Telegram media groups
    if image_limit:
        images_bytes = [all_image_bytes]
        sleep_time = 0
    else:
        images_bytes = [
            all_image_bytes[x : x + 10]
            for x in range(0, len(all_image_bytes), 10)
        ]
        image_pages = len(images_bytes)
        match image_pages:
            case 1:
                sleep_time = 0
            case 2:
                sleep_time = 1
            case 3 | 4:
                sleep_time = 2
            case _:
                sleep_time = 3

    # Check if processing is needed (only for photo mode, only for images not videos)
    if not file_mode and all_image_bytes:
        for idx, img in enumerate(all_image_bytes):
            if idx not in video_indices:
                extension = detect_image_format(img)
                if extension not in _NATIVE_EXTENSIONS:
                    processing_needed = True
                    break

    async def process_and_send_images():
        nonlocal processing_needed, processing_message, was_processed

        if processing_needed and is_private_chat and not processing_message:
            processing_message = await user_msg.reply(locale[lang]["processing"])

        if processing_needed:
            logger.info(
                f"Starting processing of {total_images} images in "
                f"{len(images_bytes)} batches for video {video_id}"
            )
            was_processed = True

        loop = asyncio.get_running_loop()
        executor = get_image_executor()
        last_part = len(images_bytes) - 1
        final = None

        image_index = 0
        for num, part_bytes in enumerate(images_bytes):
            media_group = []

            for img_bytes in part_bytes:
                current_image_number = image_index + 1
                is_video_item = image_index in video_indices
                image_index += 1

                if is_video_item:
                    # Video items: always send as document (no conversion)
                    filename = f"{video_id}_{current_image_number}.mp4"
                    buffered = BufferedInputFile(img_bytes, filename)
                    media_group.append(
                        InputMediaDocument(
                            media=buffered, disable_content_type_detection=True
                        )
                    )
                elif file_mode:
                    extension = detect_image_format(img_bytes)
                    filename = f"{video_id}_{current_image_number}{extension}"
                    buffered = BufferedInputFile(img_bytes, filename)
                    media_group.append(
                        InputMediaDocument(
                            media=buffered, disable_content_type_detection=True
                        )
                    )
                else:
                    extension = detect_image_format(img_bytes)
                    if (
                        IMAGE_CONVERSION_AVAILABLE
                        and extension not in _NATIVE_EXTENSIONS
                    ):
                        try:
                            img_bytes = await loop.run_in_executor(
                                executor, convert_image_to_jpeg_optimized, img_bytes
                            )
                            extension = ".jpg"
                        except Exception as e:
                            logger.error(
                                f"Failed to convert image {current_image_number}: {e}"
                            )

                    filename = f"{video_id}_{current_image_number}{extension}"
                    buffered = BufferedInputFile(img_bytes, filename)
                    media_group.append(
                        InputMediaPhoto(
                            media=buffered, disable_content_type_detection=True
                        )
                    )

            if num < last_part:
                await sleep(sleep_time)
                await user_msg.reply_media_group(media_group, disable_notification=True)
            else:
                final = await user_msg.reply_media_group(
                    media_group, disable_notification=True
                )

        if processing_needed:
            logger.info(
                f"Completed processing {total_images} images for video {video_id}"
            )

        return final

    final = await process_and_send_images()

    if processing_message:
        try:
            await processing_message.delete()
        except TelegramBadRequest:
            logger.debug("Processing message already deleted")
        except Exception as e:
            logger.warning(f"Unexpected error deleting processing message: {e}")

    if final and len(final) > 0:
        await final[0].reply(
            result_caption(lang, video_info.link, bool(image_limit)),
            reply_markup=video_reply_markup(video_id, lang, video_info.likes, video_info.views),
            disable_web_page_preview=True,
        )

    return was_processed
