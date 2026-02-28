import logging

from aiogram.types import BufferedInputFile

from data.config import config
from data.loader import bot
from tiktok_api import VideoInfo

logger = logging.getLogger(__name__)

STORAGE_CHANNEL_ID = config["bot"].get("storage_channel")


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

        caption_parts = [f"<a href='{video_info.link}'>Source</a>"]

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
