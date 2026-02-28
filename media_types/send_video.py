from aiogram.types import BufferedInputFile, InputMediaVideo

from data.loader import bot
from tiktok_api import VideoInfo

from .http_session import download_thumbnail
from .storage import upload_video_to_storage
from .ui import music_button, result_caption


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

        # Download thumbnail for videos > 30 seconds
        thumbnail = None
        if video_duration and video_duration > 30:
            thumbnail = await download_thumbnail(video_info.cover, video_id)

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
