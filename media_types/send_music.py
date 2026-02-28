from aiogram.types import BufferedInputFile

from data.config import locale
from tiktok_api import MusicInfo

from .http_session import _download_url


async def send_music_result(
    query_msg, music_info: MusicInfo, lang: str, group_chat: bool
) -> None:
    video_id = music_info.id
    audio_data = music_info.data
    cover_url = music_info.cover

    if isinstance(audio_data, bytes):
        audio_bytes = audio_data
    else:
        downloaded = await _download_url(audio_data)
        if downloaded is None:
            raise ValueError(f"Failed to download audio from {audio_data}")
        audio_bytes = downloaded

    cover_bytes = await _download_url(cover_url) if cover_url else None

    audio = BufferedInputFile(audio_bytes, f"{video_id}.mp3")
    cover = BufferedInputFile(cover_bytes, f"{video_id}.jpg") if cover_bytes else None

    await query_msg.reply_audio(
        audio,
        caption=f"<b>{locale[lang]['bot_tag']}</b>",
        title=music_info.title,
        performer=music_info.author,
        duration=music_info.duration,
        thumbnail=cover,
        disable_notification=group_chat,
    )
