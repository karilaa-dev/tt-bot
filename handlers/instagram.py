import logging

from aiogram.types import Message

from data.db_service import add_video
from data.loader import bot
from instagram_api import InstagramClient, InstagramMediaInfo
from media_types import send_image_result, send_video_result
from media_types.http_session import _download_url
from tiktok_api.models import VideoInfo

logger = logging.getLogger(__name__)


def _instagram_to_video_info(
    media_info: InstagramMediaInfo,
    video_bytes: bytes | None = None,
) -> VideoInfo:
    """Convert InstagramMediaInfo to a VideoInfo for the shared send pipeline."""
    if media_info.is_video:
        if video_bytes is None:
            raise ValueError("video_bytes required for single video")
        return VideoInfo(
            type="video",
            data=video_bytes,
            id=0,
            cover=media_info.thumbnail_url,
            width=None,
            height=None,
            duration=None,
            link=media_info.link,
        )

    # Carousel: collect all media URLs, track which are videos
    urls: list[str] = []
    video_indices: set[int] = set()
    for i, item in enumerate(media_info.media):
        urls.append(item.url)
        if item.type == "video":
            video_indices.add(i)

    return VideoInfo(
        type="images",
        data=urls,
        id=0,
        cover=None,
        width=None,
        height=None,
        duration=None,
        link=media_info.link,
        _video_indices=video_indices,
    )


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
        video_bytes = await _download_url(media_info.video_url)
        if not video_bytes:
            raise ConnectionError("Failed to download video")

        video_info = _instagram_to_video_info(media_info, video_bytes)
        await send_video_result(
            message.chat.id,
            video_info,
            lang,
            file_mode,
            reply_to_message_id=message.message_id,
        )
    else:
        await bot.send_chat_action(
            chat_id=message.chat.id, action="upload_photo"
        )
        image_limit = 10 if group_chat else None
        video_info = _instagram_to_video_info(media_info)
        await send_image_result(
            message, video_info, lang, file_mode, image_limit
        )

    is_images = not media_info.is_video
    try:
        await add_video(message.chat.id, instagram_url, is_images)
        logger.info(
            f"Instagram Download: CHAT {message.chat.id} - URL {instagram_url}"
        )
    except Exception as e:
        logger.error(f"Can't write into database: {e}")
