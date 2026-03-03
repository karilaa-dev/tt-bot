import logging

from aiogram.types import BufferedInputFile

from data.config import config
from data.loader import bot
from tiktok_api import VideoInfo

logger = logging.getLogger(__name__)

STORAGE_CHANNEL_ID = config["bot"].get("storage_channel")


def _build_storage_caption(
    source_link: str,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
) -> str:
    caption_parts = [f"<a href='{source_link}'>Source</a>"]
    if user_id:
        user_link = (
            f'<b><a href="tg://user?id={user_id}">{full_name or "User"}</a></b>'
        )
        caption_parts.append("")
        caption_parts.append(user_link)
        if username:
            caption_parts.append(f"@{username}")
        caption_parts.append(f"<code>{user_id}</code>")
    return "\n".join(caption_parts)


async def upload_photo_to_storage(
    photo_data: bytes,
    source_link: str,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
) -> str | None:
    """Upload photo to storage channel and return the file_id, or None on failure."""
    if not STORAGE_CHANNEL_ID:
        logger.warning("STORAGE_CHANNEL_ID not configured, cannot upload for inline")
        return None

    try:
        photo_file = BufferedInputFile(photo_data, filename="inline_photo.jpg")
        caption = _build_storage_caption(source_link, user_id, username, full_name)

        message = await bot.send_photo(
            chat_id=STORAGE_CHANNEL_ID,
            photo=photo_file,
            caption=caption,
            parse_mode="HTML",
            disable_notification=True,
        )
        if message.photo:
            return message.photo[-1].file_id
        return None
    except Exception as e:
        logger.exception(f"Failed to upload photo to storage channel: {e}")
        return None


async def upload_video_to_storage(
    video_data: bytes,
    video_info: VideoInfo,
    user_id: int | None = None,
    username: str | None = None,
    full_name: str | None = None,
    thumbnail: BufferedInputFile | None = None,
) -> str | None:
    """Upload video to storage channel and return the file_id, or None on failure."""
    if not STORAGE_CHANNEL_ID:
        logger.warning("STORAGE_CHANNEL_ID not configured, cannot upload for inline")
        return None

    try:
        video_file = BufferedInputFile(video_data, filename=f"{video_info.id}.mp4")
        caption = _build_storage_caption(
            video_info.link, user_id, username, full_name
        )

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
