from asyncio import sleep
import asyncio
import io
import concurrent.futures
import logging

import aiohttp
from aiohttp import ClientTimeout
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale, config
from data.loader import bot
from tiktok_api import (
    TikTokClient,
    TikTokError,
    TikTokDeletedError,
    TikTokPrivateError,
    TikTokNetworkError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
    TikTokVideoTooLongError,
    VideoInfo,
    MusicInfo,
)

# Configure logger
logger = logging.getLogger(__name__)

# Persistent ProcessPoolExecutor for image conversion
# This prevents "cannot schedule new futures after shutdown" errors under high load
_image_executor: concurrent.futures.ProcessPoolExecutor | None = None


def get_image_executor() -> concurrent.futures.ProcessPoolExecutor:
    """Get or create a persistent ProcessPoolExecutor for image conversion."""
    global _image_executor
    if _image_executor is None:
        _image_executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)
    return _image_executor


# Storage channel for uploading videos to get file_id (required for inline messages)
STORAGE_CHANNEL_ID = config["bot"].get("storage_channel")

# Shared aiohttp session for cover/thumbnail downloads
# Reusing sessions is more efficient than creating new ones per request
_http_session: aiohttp.ClientSession | None = None

# Timeout configuration for HTTP requests
_HTTP_TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=20)


def _get_http_session() -> aiohttp.ClientSession:
    """Get or create a shared aiohttp ClientSession for HTTP requests.

    The session is configured with:
    - 30s total timeout (prevents hanging requests)
    - 10s connect timeout
    - 20s read timeout
    """
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=20,  # Per-host limit to avoid overwhelming single CDN
            ttl_dns_cache=300,  # Cache DNS for 5 minutes
            enable_cleanup_closed=True,
        )
        _http_session = aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT,
            connector=connector,
        )
    return _http_session


async def close_http_session() -> None:
    """Close the shared aiohttp session. Call on application shutdown.

    This should be called in the main.py shutdown sequence to properly
    release all connections and prevent socket leaks.
    """
    global _http_session
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        _http_session = None


async def _download_url(url: str) -> bytes | None:
    """Download content from a URL using the shared HTTP session.

    Args:
        url: URL to download from

    Returns:
        Downloaded bytes or None if the download failed
    """
    try:
        session = _get_http_session()
        async with session.get(url, allow_redirects=True) as response:
            if response.status == 200:
                return await response.read()
    except Exception as e:
        logger.warning(f"Failed to download from {url}: {e}")
    return None


async def download_thumbnail(
    cover_url: str | None, video_id: int
) -> BufferedInputFile | None:
    """Download cover image for use as video thumbnail.

    Only used for videos longer than 1 minute to provide a proper preview.

    Args:
        cover_url: URL of the cover image
        video_id: Video ID for filename

    Returns:
        BufferedInputFile with thumbnail data, or None if download failed
    """
    if not cover_url:
        return None
    cover_bytes = await _download_url(cover_url)
    if cover_bytes:
        return BufferedInputFile(cover_bytes, f"{video_id}_thumb.jpg")
    return None


async def upload_video_to_storage(
    video_data: bytes,
    video_info: VideoInfo,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
    thumbnail: BufferedInputFile | None = None,
) -> str | None:
    """
    Upload video to storage channel to get a file_id.
    This is required for inline messages since Telegram doesn't support
    uploading new files via BufferedInputFile for inline message edits.

    Args:
        video_data: Video bytes to upload
        video_info: VideoInfo object containing video metadata
        user_id: Telegram user ID who requested the video (optional)
        username: Telegram username who requested the video (optional)
        full_name: Telegram user's full name (optional)
        thumbnail: Video thumbnail for videos > 1 minute (optional)

    Returns:
        file_id string if successful, None otherwise
    """
    if not STORAGE_CHANNEL_ID:
        logger.warning("STORAGE_CHANNEL_ID not configured, cannot upload for inline")
        return None

    try:
        video_file = BufferedInputFile(video_data, filename=f"{video_info.id}.mp4")

        # Build caption with Source link and user info (same format as new user log)
        video_link = f"https://www.tiktok.com/@/video/{video_info.id}"
        caption_parts = [f"<a href='{video_link}'>Source</a>"]

        # Add user info in same format as new user registration log
        if user_id:
            user_link = (
                f'<b><a href="tg://user?id={user_id}">{full_name or "User"}</a></b>'
            )
            caption_parts.append("")  # Empty line separator
            caption_parts.append(user_link)
            if username:
                caption_parts.append(f"@{username}")
            caption_parts.append(f"<code>{user_id}</code>")

        caption = "\n".join(caption_parts)

        message = await bot.send_video(
            chat_id=STORAGE_CHANNEL_ID,
            video=video_file,
            caption=caption,
            parse_mode="HTML",
            disable_notification=True,
            width=video_info.width,
            height=video_info.height,
            duration=video_info.duration,
            thumbnail=thumbnail,
            supports_streaming=True,
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
    elif isinstance(error, TikTokInvalidLinkError):
        return lang_dict.get("error_invalid_link", "Invalid video link.")
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
    elif isinstance(error, TikTokVideoTooLongError):
        return lang_dict.get(
            "error_too_long", "This video is too long (max 30 minutes)."
        )
    else:  # TikTokExtractionError and any other
        return lang_dict.get(
            "error", "An error occurred while processing your request."
        )


# Add PIL imports for image processing
try:
    from PIL import Image
    import pillow_heif

    # Register HEIF opener with pillow once at module load
    # This avoids repeated registration overhead per-image
    pillow_heif.register_heif_opener()
    IMAGE_CONVERSION_AVAILABLE = True
    _HEIF_REGISTERED = True
except ImportError:
    IMAGE_CONVERSION_AVAILABLE = False
    _HEIF_REGISTERED = False


def music_button(video_id: int, lang: str) -> InlineKeyboardMarkup:
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]["get_sound"], callback_data=f"id/{video_id}")
    return keyb.as_markup()


def result_caption(lang: str, link: str, group_warning: bool | None = None) -> str:
    result = locale[lang]["result"].format(locale[lang]["bot_tag"], link)
    if group_warning:
        result += locale[lang]["group_warning"]
    return result


async def send_video_result(
    targed_id: int | str,
    video_info: VideoInfo,
    lang: str,
    file_mode: bool,
    inline_message: bool = False,
    reply_to_message_id: int | None = None,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
) -> None:
    video_id = video_info.id
    video_data = video_info.data
    video_duration = video_info.duration

    # For inline messages, we must upload to storage channel first to get file_id
    # since Telegram doesn't support uploading new files for inline message edits
    if inline_message:
        if not isinstance(video_data, bytes):
            raise ValueError("Video data must be bytes for inline messages")

        # Download thumbnail for videos > 1 minute
        thumbnail = None
        if video_duration and video_duration > 60:
            thumbnail = await download_thumbnail(video_info.cover, video_id)

        # Upload to storage channel to get file_id
        file_id = await upload_video_to_storage(
            video_data,
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
            caption=result_caption(lang, video_info.link),
            width=video_info.width,
            height=video_info.height,
            duration=video_duration,
            supports_streaming=True,
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
        # Download thumbnail for videos > 1 minute
        thumbnail = None
        if video_duration and video_duration > 60:
            thumbnail = await download_thumbnail(video_info.cover, video_id)

        await bot.send_video(
            chat_id=targed_id,
            video=video_file,
            caption=result_caption(lang, video_info.link),
            height=video_info.height,
            width=video_info.width,
            duration=video_duration,
            thumbnail=thumbnail,
            supports_streaming=True,
            reply_markup=music_button(video_id, lang),
            reply_to_message_id=reply_to_message_id,
        )


async def send_music_result(
    query_msg, music_info: MusicInfo, lang: str, group_chat: bool
) -> None:
    video_id = music_info.id
    audio_data = music_info.data
    cover_url = music_info.cover

    # Handle audio data - could be bytes or URL
    if isinstance(audio_data, bytes):
        audio_bytes = audio_data
    else:
        # Fallback: try to download from URL using shared session
        downloaded = await _download_url(audio_data)
        if downloaded is None:
            raise ValueError(f"Failed to download audio from {audio_data}")
        audio_bytes = downloaded

    # Download cover from URL using shared session
    cover_bytes = await _download_url(cover_url) if cover_url else None

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


async def detect_image_processing_needed(
    image_link: str, client: TikTokClient, video_info: VideoInfo
) -> bool:
    """
    Check if an image needs processing by examining its format.
    Returns True if the image is not in JPEG or WebP format.

    Uses HTTP Range request to fetch only the first 20 bytes for efficient
    format detection without downloading the entire image.

    Args:
        image_link: URL of the image to check
        client: TikTokClient instance for authenticated downloads
        video_info: VideoInfo containing download context

    Returns:
        True if image needs processing (conversion), False otherwise
    """
    try:
        # Use Range request to fetch only first 20 bytes (efficient)
        extension = await client.detect_image_format(image_link, video_info)
        return extension not in [".jpg", ".webp"]
    except Exception:
        # If we can't check, assume processing might be needed
        return True


async def download_image(
    image_link: str, client: TikTokClient, video_info: VideoInfo
) -> bytes:
    """
    Download image data using yt-dlp client.

    Uses the same authentication context (cookies, headers) that was
    established during video info extraction.

    Args:
        image_link: URL of the image to download
        client: TikTokClient instance for authenticated downloads
        video_info: VideoInfo containing download context from extraction

    Returns:
        bytes: Raw image data

    Raises:
        TikTokNetworkError: If the download fails
    """
    return await client.download_image(image_link, video_info)


async def download_images_parallel(
    image_urls: list[str],
    client: TikTokClient,
    video_info: VideoInfo,
    max_concurrent: int | None = None,
) -> list[bytes | BaseException]:
    """
    Download multiple images in parallel with concurrency limit.

    Uses semaphore to prevent overwhelming TikTok CDN while maximizing throughput.
    This is significantly faster than sequential downloads for slideshows.

    Args:
        image_urls: List of image URLs to download
        client: TikTokClient instance for authenticated downloads
        video_info: VideoInfo containing download context
        max_concurrent: Maximum concurrent downloads. If None, uses config value.

    Returns:
        List of image bytes (or exceptions for failed downloads)
    """
    if max_concurrent is None:
        perf_config = config.get("performance")
        max_concurrent = perf_config["max_concurrent_images"] if perf_config else 20

    semaphore = asyncio.Semaphore(max_concurrent)

    async def download_with_limit(url: str) -> bytes:
        async with semaphore:
            return await client.download_image(url, video_info)

    return await asyncio.gather(
        *[download_with_limit(url) for url in image_urls],
        return_exceptions=True,  # Don't fail all if one fails
    )


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


async def convert_single_image(
    image_link: str,
    file_name: str,
    executor,
    loop,
    client: TikTokClient,
    video_info: VideoInfo,
):
    """
    Download and convert a single image to JPEG format if needed.

    Args:
        image_link: URL of the image to download
        file_name: Base filename for the image
        executor: ProcessPoolExecutor for image conversion
        loop: Event loop for running executor tasks
        client: TikTokClient instance for authenticated downloads
        video_info: VideoInfo containing download context

    Returns:
        BufferedInputFile with the processed image data
    """
    # Download image data using yt-dlp client
    image_data = await download_image(image_link, client, video_info)

    # Check and convert image if needed
    processed_data, extension = await check_and_convert_image(
        image_data, executor, loop
    )

    # Create filename with correct extension
    final_filename = f"{file_name.rsplit('.', 1)[0]}{extension}"

    image_bytes = BufferedInputFile(processed_data, final_filename)
    return image_bytes


async def send_image_result(
    user_msg,
    video_info: VideoInfo,
    lang: str,
    file_mode: bool,
    image_limit: int | None,
    client: TikTokClient,
) -> bool:
    video_id = video_info.id
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
            processing_needed = await detect_image_processing_needed(
                first_image_link, client, video_info
            )

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

        # Use persistent executor to avoid "cannot schedule new futures after shutdown" errors
        loop = asyncio.get_running_loop()
        executor = get_image_executor()
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
                        image_link,
                        file_name=f"{video_id}_{current_image_number}",
                        client=client,
                        video_info=video_info,
                    )
                else:
                    task = convert_single_image(
                        image_link,
                        f"{video_id}_{current_image_number}",
                        executor,
                        loop,
                        client=client,
                        video_info=video_info,
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
                        InputMediaPhoto(media=data, disable_content_type_detection=True)
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
                f"Completed processing {total_images} images in {len(images)} batches for video {video_id}"
            )

        return final

    final = await process_images_batch()

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


def convert_image_to_jpeg_optimized(image_data: bytes) -> bytes:
    """
    Convert any image data to JPEG format with a focus on minimizing
    computing power and achieving a good size/quality ratio.

    Note: pillow_heif.register_heif_opener() is called once at module load,
    not per-image, for better performance.
    """
    try:
        # HEIF opener is already registered at module level
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


def detect_image_format(image_data: bytes) -> str:
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


async def get_image_data_raw(
    image_link: str, file_name: str, client: TikTokClient, video_info: VideoInfo
) -> BufferedInputFile:
    """
    Download image data and create BufferedInputFile with correct extension
    based on the actual image format, without any conversion.

    Uses yt-dlp client for authenticated downloads.

    Args:
        image_link: URL of the image to download
        file_name: Base filename for the image
        client: TikTokClient instance for authenticated downloads
        video_info: VideoInfo containing download context

    Returns:
        BufferedInputFile with the raw image data
    """
    # Download image using yt-dlp client
    image_data = await download_image(image_link, client, video_info)

    # Detect image format and get correct extension
    extension = detect_image_format(image_data)

    # Create filename with correct extension
    final_filename = f"{file_name}{extension}"

    image_bytes = BufferedInputFile(image_data, final_filename)
    return image_bytes


async def get_image_data(
    image_link: str, file_name: str, client: TikTokClient, video_info: VideoInfo
) -> BufferedInputFile:
    """Get image data with conversion if needed - for compatibility.

    Uses yt-dlp client for authenticated downloads.
    """
    # Download image using yt-dlp client
    image_data = await download_image(image_link, client, video_info)

    # Detect image format
    extension = detect_image_format(image_data)

    # Only convert if it's not JPEG or WebP
    if IMAGE_CONVERSION_AVAILABLE and image_data and extension not in [".jpg", ".webp"]:
        # Use shared executor for efficiency
        loop = asyncio.get_running_loop()
        executor = get_image_executor()
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
