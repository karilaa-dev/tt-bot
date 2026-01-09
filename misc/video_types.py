from asyncio import sleep
import asyncio
import io
import concurrent.futures
import logging

import aiohttp
from aiogram.types import (
    BufferedInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale, config
from data.loader import bot
from tiktok_api import (
    TikTokError,
    TikTokDeletedError,
    TikTokPrivateError,
    TikTokNetworkError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokExtractionError,
    VideoInfo,
    MusicInfo,
)

# Configure logger
logger = logging.getLogger(__name__)

# Storage channel for uploading videos to get file_id (required for inline messages)
STORAGE_CHANNEL_ID = config["bot"].get("storage_channel")


async def upload_video_to_storage(video_data: bytes, video_id: int) -> str | None:
    """
    Upload video to storage channel to get a file_id.
    This is required for inline messages since Telegram doesn't support
    uploading new files via BufferedInputFile for inline message edits.

    Args:
        video_data: Video bytes to upload
        video_id: Video ID for filename

    Returns:
        file_id string if successful, None otherwise
    """
    if not STORAGE_CHANNEL_ID:
        logger.warning("STORAGE_CHANNEL_ID not configured, cannot upload for inline")
        return None

    try:
        video_file = BufferedInputFile(video_data, filename=f"{video_id}.mp4")
        message = await bot.send_video(
            chat_id=STORAGE_CHANNEL_ID,
            video=video_file,
            disable_notification=True,
        )
        if message.video:
            return message.video.file_id
        return None
    except Exception as e:
        logger.exception(f"Failed to upload video to storage channel: {e}")
        return None


def get_error_message(error: TikTokError, lang: str) -> str:
    """Map TikTok exceptions to localized error messages."""
    # Safely resolve language dict with fallback to English or empty dict
    lang_dict = locale.get(lang) or locale.get("en") or {}

    if isinstance(error, TikTokDeletedError):
        return lang_dict.get("error_deleted", "This video has been deleted.")
    elif isinstance(error, TikTokPrivateError):
        return lang_dict.get("error_private", "This video is private.")
    elif isinstance(error, TikTokNetworkError):
        return lang_dict.get("error_network", "Network error occurred.")
    elif isinstance(error, TikTokRateLimitError):
        return lang_dict.get(
            "error_rate_limit", "Rate limit exceeded. Please try again later."
        )
    elif isinstance(error, TikTokRegionError):
        return lang_dict.get(
            "error_region", "This video is not available in your region."
        )
    else:  # TikTokExtractionError and any other
        return lang_dict.get(
            "error", "An error occurred while processing your request."
        )


# Add PIL imports for image processing
try:
    from PIL import Image
    import pillow_heif

    # Register HEIF opener with pillow
    pillow_heif.register_heif_opener()
    IMAGE_CONVERSION_AVAILABLE = True
except ImportError:
    IMAGE_CONVERSION_AVAILABLE = False


def music_button(video_id, lang):
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]["get_sound"], callback_data=f"id/{video_id}")
    return keyb.as_markup()


def result_caption(lang, link, group_warning=None):
    result = locale[lang]["result"].format(locale[lang]["bot_tag"], link)
    if group_warning:
        result += locale[lang]["group_warning"]
    return result


async def send_video_result(
    targed_id,
    video_info: VideoInfo,
    lang,
    file_mode,
    inline_message=False,
    reply_to_message_id=None,
):
    video_id = video_info.id
    video_data = video_info.data
    video_duration = video_info.duration

    # For inline messages, we must upload to storage channel first to get file_id
    # since Telegram doesn't support uploading new files for inline message edits
    if inline_message:
        if not isinstance(video_data, bytes):
            raise ValueError("Video data must be bytes for inline messages")

        # Upload to storage channel to get file_id
        file_id = await upload_video_to_storage(video_data, video_id)
        if not file_id:
            raise ValueError(
                "Failed to upload video to storage. "
                "Make sure STORAGE_CHANNEL_ID is configured in .env"
            )

        video_media = InputMediaVideo(
            media=file_id, caption=result_caption(lang, video_info.link)
        )
        await bot.edit_message_media(inline_message_id=targed_id, media=video_media)
        return

    # Create BufferedInputFile from bytes for regular messages
    if isinstance(video_data, bytes):
        video_file = BufferedInputFile(video_data, filename=f"{video_id}.mp4")
    else:
        video_file = video_data  # Fallback to URL if not bytes

    if file_mode:
        await bot.send_document(
            chat_id=targed_id,
            document=video_file,
            caption=result_caption(lang, video_info.link),
            reply_markup=music_button(video_id, lang),
            reply_to_message_id=reply_to_message_id,
            disable_content_type_detection=True,
        )
    else:
        await bot.send_video(
            chat_id=targed_id,
            video=video_file,
            caption=result_caption(lang, video_info.link),
            height=video_info.height,
            width=video_info.width,
            duration=video_duration,
            reply_markup=music_button(video_id, lang),
            reply_to_message_id=reply_to_message_id,
        )


async def send_music_result(query_msg, music_info: MusicInfo, lang, group_chat):
    video_id = music_info.id
    audio_data = music_info.data
    cover_url = music_info.cover

    # Handle audio data - could be bytes or URL
    if isinstance(audio_data, bytes):
        audio_bytes = audio_data
    else:
        # Fallback: try to download from URL
        async with aiohttp.ClientSession() as client:
            async with client.get(audio_data, allow_redirects=True) as audio_request:
                audio_bytes = await audio_request.read()

    # Download cover from URL
    cover_bytes = None
    if cover_url:
        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(cover_url, allow_redirects=True) as cover_request:
                    if cover_request.status == 200:
                        cover_bytes = await cover_request.read()
        except Exception as e:
            logger.warning(f"Failed to download cover: {e}")

    audio = BufferedInputFile(audio_bytes, f"{video_id}.mp3")
    cover = BufferedInputFile(cover_bytes, f"{video_id}.jpg") if cover_bytes else None

    caption = f"<b>{locale[lang]['bot_tag']}</b>"
    # Send music
    await query_msg.reply_audio(
        audio,
        caption=caption,
        title=music_info.title,
        performer=music_info.author,
        duration=music_info.duration,
        thumbnail=cover,
        disable_notification=group_chat,
    )


async def detect_image_processing_needed(image_link):
    """
    Check if an image needs processing by examining its format.
    Returns True if the image is not in JPEG or WebP format.
    """
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                image_link, headers={"Range": "bytes=0-20"}
            ) as response:
                if response.status == 206:  # Partial content
                    header_bytes = await response.read()
                    extension = detect_image_format(header_bytes)
                    return extension not in [".jpg", ".webp"]
    except:
        # If we can't check, assume processing might be needed
        return True
    return False


async def download_image(image_link):
    """
    Download image data from a URL.

    Args:
        image_link: URL of the image to download

    Returns:
        bytes: Raw image data

    Raises:
        aiohttp.ClientResponseError: If the download fails
    """
    async with aiohttp.ClientSession() as client:
        async with client.get(image_link, allow_redirects=True) as image_request:
            # Let aiohttp handle the error properly with all required arguments
            image_request.raise_for_status()
            return await image_request.read()


async def check_and_convert_image(image_data, executor, loop):
    """
    Check image type and convert to JPEG if it's not WebP or JPEG.

    Args:
        image_data: Raw image data bytes
        executor: ProcessPoolExecutor for image conversion
        loop: Event loop for running executor tasks

    Returns:
        tuple: (converted_image_data, extension)
    """
    # Detect image format
    extension = detect_image_format(image_data)

    # Convert to JPEG if it's not WebP or JPEG
    if IMAGE_CONVERSION_AVAILABLE and image_data and extension not in [".jpg", ".webp"]:
        try:
            # Run conversion in shared executor
            converted_data = await loop.run_in_executor(
                executor, convert_image_to_jpeg_optimized, image_data
            )
            return converted_data, ".jpg"  # After conversion, it's always JPEG
        except Exception as e:
            logger.error(f"Failed to convert image: {e}")
            # Continue with original data if conversion fails
            return image_data, extension

    # Return original data if no conversion needed or not available
    return image_data, extension


async def convert_single_image(image_link, file_name, executor, loop):
    """
    Download and convert a single image to JPEG format if needed.

    Args:
        image_link: URL of the image to download
        file_name: Base filename for the image
        executor: ProcessPoolExecutor for image conversion
        loop: Event loop for running executor tasks

    Returns:
        BufferedInputFile with the processed image data
    """
    # Download image data
    image_data = await download_image(image_link)

    # Check and convert image if needed
    processed_data, extension = await check_and_convert_image(
        image_data, executor, loop
    )

    # Create filename with correct extension
    final_filename = f"{file_name.rsplit('.', 1)[0]}{extension}"

    image_bytes = BufferedInputFile(processed_data, final_filename)
    return image_bytes


async def send_image_result(
    user_msg, video_info: VideoInfo, lang, file_mode, image_limit
):
    video_id = video_info.id
    image_number = 0
    # Use image_urls property for slideshows
    image_data = video_info.image_urls
    if image_limit:
        images = [image_data[:image_limit]]
        sleep_time = 0
    else:
        images = [image_data[x : x + 10] for x in range(0, len(image_data), 10)]
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

    # Calculate total number of images and check if processing is needed
    total_images = sum(len(part) for part in images)
    processing_needed = False
    processing_message = None
    was_processed = False  # Track if any processing actually occurred

    # Only check and send message if we're in photo mode (conversion mode) and not in groups
    is_private_chat = user_msg.chat.type == "private"

    if not file_mode:
        # Quick check if processing is needed by checking only the first image
        first_image_link = images[0][0] if images and images[0] else None
        if first_image_link:
            processing_needed = await detect_image_processing_needed(first_image_link)

    # Function to process images with optional forced processing
    async def process_images_batch():
        nonlocal processing_needed, processing_message, was_processed

        # Send processing message only in private chats if processing is needed
        if processing_needed and is_private_chat and not processing_message:
            processing_message = await user_msg.reply(locale[lang]["processing"])

        if processing_needed:
            logger.info(
                f"Starting parallel processing of {total_images} images in {len(images)} batches for video {video_id}"
            )
            was_processed = True  # Mark that processing occurred

        # Create a single thread pool for all image processing
        loop = asyncio.get_event_loop()
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(total_images, 4)
        ) as executor:
            last_part = len(images) - 1
            final = None

            for num, part in enumerate(images):
                media_group = []

                # Create tasks for parallel processing of images in this part
                tasks = []
                for i, image_link in enumerate(part):
                    current_image_number = (
                        (num * 10) + i + 1
                    )  # Calculate correct image number
                    if file_mode:
                        task = get_image_data_raw(
                            image_link, file_name=f"{video_id}_{current_image_number}"
                        )
                    else:
                        task = convert_single_image(
                            image_link,
                            f"{video_id}_{current_image_number}",
                            executor,
                            loop,
                        )
                    tasks.append(task)

                # Process all images in this part concurrently
                image_data_list = await asyncio.gather(*tasks)

                # Create media group from processed images
                for data in image_data_list:
                    if file_mode:
                        media_group.append(
                            InputMediaDocument(
                                media=data, disable_content_type_detection=True
                            )
                        )
                    else:
                        media_group.append(
                            InputMediaPhoto(
                                media=data, disable_content_type_detection=True
                            )
                        )

                if num < last_part:
                    await sleep(sleep_time)
                    await user_msg.reply_media_group(
                        media_group, disable_notification=True
                    )
                else:
                    final = await user_msg.reply_media_group(
                        media_group, disable_notification=True
                    )

        if processing_needed:
            logger.info(
                f"Completed processing {total_images} images in {len(images)} batches for video {video_id}"
            )

        return final

    final = await process_images_batch()

    # Delete processing message after all images are sent
    if processing_message:
        try:
            await processing_message.delete()
        except:
            pass  # Ignore errors if message can't be deleted

    await final[0].reply(
        result_caption(lang, video_info.link, bool(image_limit)),
        reply_markup=music_button(video_id, lang),
        disable_web_page_preview=True,
    )

    return was_processed


def convert_image_to_jpeg_optimized(image_data):
    """
    Convert any image data to JPEG format with a focus on minimizing
    computing power and achieving a good size/quality ratio.
    """
    try:
        # Register HEIF opener with Pillow
        pillow_heif.register_heif_opener()

        with Image.open(io.BytesIO(image_data)) as img:
            # 1. Handle Mode Conversion (as in your script, good for minimizing processing)
            #    Pillow-heif usually loads HEIC into RGB or RGBA directly.
            #    If it's RGBA and you don't need transparency, convert to RGB.
            if img.mode == "RGBA":
                # Create a new RGB image and paste the RGBA image onto it
                # using the alpha channel as a mask. This is generally faster
                # than img.convert('RGB') if you don't care about blending
                # with a specific background color. For HEIC to JPEG,
                # a white background is common if transparency is discarded.
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])  # 3 is the alpha channel
                img = background
            elif img.mode != "RGB":  # Ensure it's RGB for JPEG
                img = img.convert("RGB")

            # 2. Save to JPEG
            output = io.BytesIO()
            img.save(
                output,
                format="JPEG",
                quality=75,  # Good balance. Adjust 70-85 as needed.
                optimize=False,  # Saves a bit of CPU by not making an extra pass.
                subsampling=2,  # Corresponds to 4:2:0 chroma subsampling - good compression.
                progressive=False,  # Generally faster to encode non-progressive.
            )
            return output.getvalue()
    except Exception as e:
        logger.error(f"Image to JPEG conversion failed: {e}")
        # Depending on your error handling strategy, you might want to:
        # return None, or raise the exception, or return original_data
        return image_data  # Returning original data as in your example


def detect_image_format(image_data):
    """Detect image format from magic bytes and return appropriate extension."""
    if image_data.startswith(b"\xff\xd8\xff"):
        # JPEG
        return ".jpg"
    elif image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        # WebP
        return ".webp"
    elif image_data[4:12] == b"ftypheic" or image_data[4:12] == b"ftypmif1":
        # HEIC
        return ".heic"
    else:
        # Unknown format, default to jpg
        return ".jpg"


async def get_image_data_raw(image_link, file_name):
    """
    Download image data and create BufferedInputFile with correct extension
    based on the actual image format, without any conversion.
    """
    async with aiohttp.ClientSession() as client:
        async with client.get(image_link, allow_redirects=True) as image_request:
            if image_request.status < 200 or image_request.status >= 300:
                raise aiohttp.ClientResponseError(
                    status=image_request.status,
                    message=f"Failed to fetch image from {image_link}. HTTP status: {image_request.status}",
                )
            image_data = await image_request.read()

    # Detect image format and get correct extension
    extension = detect_image_format(image_data)

    # Create filename with correct extension
    final_filename = f"{file_name}{extension}"

    image_bytes = BufferedInputFile(image_data, final_filename)
    return image_bytes


async def get_image_data(image_link, file_name):
    """Get image data with conversion if needed - for compatibility"""
    async with aiohttp.ClientSession() as client:
        async with client.get(image_link, allow_redirects=True) as image_request:
            if image_request.status < 200 or image_request.status >= 300:
                raise aiohttp.ClientResponseError(
                    status=image_request.status,
                    message=f"Failed to fetch image from {image_link}. HTTP status: {image_request.status}",
                )
            image_data = await image_request.read()

    # Detect image format
    extension = detect_image_format(image_data)

    # Only convert if it's not JPEG or WebP
    if IMAGE_CONVERSION_AVAILABLE and image_data and extension not in [".jpg", ".webp"]:
        # Not a JPEG or WebP, convert it in a separate process for speed
        loop = asyncio.get_event_loop()
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            try:
                # Run conversion in separate process
                converted_data = await loop.run_in_executor(
                    executor, convert_image_to_jpeg_optimized, image_data
                )
                image_data = converted_data
                extension = ".jpg"  # After conversion, it's always JPEG
            except Exception as e:
                logger.error(f"Failed to convert image {file_name}: {e}")
                # Continue with original data if conversion fails

    # Create filename with correct extension
    final_filename = f"{file_name.rsplit('.', 1)[0]}{extension}"

    image_bytes = BufferedInputFile(image_data, final_filename)
    return image_bytes
