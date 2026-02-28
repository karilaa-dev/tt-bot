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

from .image_processing import (
    IMAGE_CONVERSION_AVAILABLE,
    check_and_convert_image,
    convert_image_to_jpeg_optimized,
    detect_image_format,
    get_image_executor,
)
from .ui import music_button, result_caption

logger = logging.getLogger(__name__)


async def detect_image_processing_needed(
    image_link: str, client: TikTokClient, video_info: VideoInfo
) -> bool:
    """Check if an image needs processing by examining its format.

    Uses HTTP Range request to fetch only the first 20 bytes for efficient
    format detection without downloading the entire image.
    """
    try:
        extension = await client.detect_image_format(image_link, video_info)
        return extension not in [".jpg", ".webp"]
    except Exception:
        return True


async def download_image(
    image_link: str, client: TikTokClient, video_info: VideoInfo
) -> bytes:
    """Download image data using yt-dlp client.

    Uses the same authentication context (cookies, headers) that was
    established during video info extraction.
    """
    return await client.download_image(image_link, video_info)


async def download_images_parallel(
    image_urls: list[str],
    client: TikTokClient,
    video_info: VideoInfo,
) -> list[bytes | BaseException]:
    """Download multiple images in parallel with no concurrency limit."""
    return await asyncio.gather(
        *[client.download_image(url, video_info) for url in image_urls],
        return_exceptions=True,
    )


async def convert_single_image(
    image_link: str,
    file_name: str,
    executor,
    loop,
    client: TikTokClient,
    video_info: VideoInfo,
) -> BufferedInputFile:
    """Download and convert a single image to JPEG format if needed."""
    image_data = await download_image(image_link, client, video_info)
    processed_data, extension = await check_and_convert_image(
        image_data, executor, loop
    )
    final_filename = f"{file_name.rsplit('.', 1)[0]}{extension}"
    return BufferedInputFile(processed_data, final_filename)


async def send_image_result(
    user_msg,
    video_info: VideoInfo,
    lang: str,
    file_mode: bool,
    image_limit: int | None,
    client: TikTokClient,
) -> bool:
    """Send slideshow images to the user.

    Downloads all images first using retry strategy (retry individual
    failed images with proxy rotation), then processes and sends them.

    Returns:
        True if image processing (conversion) was performed
    """
    video_id = video_info.id
    image_urls = video_info.image_urls

    if image_limit:
        image_urls = image_urls[:image_limit]

    total_images = len(image_urls)
    processing_needed = False
    processing_message = None
    was_processed = False

    is_private_chat = user_msg.chat.type == "private"

    # Download all images with retry
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
        # Fallback: download using legacy method (no retry)
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

    # Check if processing is needed (only for photo mode)
    if not file_mode and all_image_bytes:
        first_image = all_image_bytes[0]
        extension = detect_image_format(first_image)
        processing_needed = extension not in [".jpg", ".webp"]

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
                image_index += 1

                extension = detect_image_format(img_bytes)

                if file_mode:
                    filename = f"{video_id}_{current_image_number}{extension}"
                    buffered = BufferedInputFile(img_bytes, filename)
                    media_group.append(
                        InputMediaDocument(
                            media=buffered, disable_content_type_detection=True
                        )
                    )
                else:
                    if (
                        IMAGE_CONVERSION_AVAILABLE
                        and extension not in [".jpg", ".webp"]
                    ):
                        try:
                            converted = await loop.run_in_executor(
                                executor, convert_image_to_jpeg_optimized, img_bytes
                            )
                            img_bytes = converted
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

    # Delete processing message after all images are sent
    if processing_message:
        try:
            await processing_message.delete()
        except TelegramBadRequest:
            logger.debug("Processing message already deleted")
        except Exception as e:
            logger.warning(f"Unexpected error deleting processing message: {e}")

    # Reply with caption to the first message in the final batch
    if final and len(final) > 0:
        await final[0].reply(
            result_caption(lang, video_info.link, bool(image_limit)),
            reply_markup=music_button(video_id, lang),
            disable_web_page_preview=True,
        )

    return was_processed


async def get_image_data_raw(
    image_link: str, file_name: str, client: TikTokClient, video_info: VideoInfo
) -> BufferedInputFile:
    """Download image data and create BufferedInputFile with correct extension
    based on the actual image format, without any conversion.
    """
    image_data = await download_image(image_link, client, video_info)
    extension = detect_image_format(image_data)
    final_filename = f"{file_name}{extension}"
    return BufferedInputFile(image_data, final_filename)


async def get_image_data(
    image_link: str, file_name: str, client: TikTokClient, video_info: VideoInfo
) -> BufferedInputFile:
    """Get image data with conversion if needed."""
    image_data = await download_image(image_link, client, video_info)
    extension = detect_image_format(image_data)

    if IMAGE_CONVERSION_AVAILABLE and image_data and extension not in [".jpg", ".webp"]:
        loop = asyncio.get_running_loop()
        executor = get_image_executor()
        try:
            converted_data = await loop.run_in_executor(
                executor, convert_image_to_jpeg_optimized, image_data
            )
            image_data = converted_data
            extension = ".jpg"
        except Exception as e:
            logger.error(f"Failed to convert image {file_name}: {e}")

    final_filename = f"{file_name.rsplit('.', 1)[0]}{extension}"
    return BufferedInputFile(image_data, final_filename)
