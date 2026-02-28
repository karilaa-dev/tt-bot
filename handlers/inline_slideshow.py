import asyncio
import logging
import re
from dataclasses import dataclass, field

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)

from data.loader import bot
from instagram_api import INSTAGRAM_URL_REGEX, InstagramClient
from media_types.http_session import _download_url
from media_types.image_processing import ensure_native_format
from media_types.storage import (
    STORAGE_CHANNEL_ID,
    _build_storage_caption,
    upload_photo_to_storage,
)
from media_types.ui import result_caption
from misc.utils import lang_func
from tiktok_api import TikTokClient, ProxyManager
from tiktok_api.models import VideoInfo

logger = logging.getLogger(__name__)

slideshow_router = Router(name=__name__)

_SESSION_TTL = 600  # 10 minutes


@dataclass
class SlideshowSession:
    image_urls: list[str]
    file_ids: dict[int, str]  # index -> cached Telegram file_id
    current_index: int
    lang: str
    source_link: str
    user_id: int
    username: str | None
    full_name: str | None
    _cleanup_task: asyncio.Task | None = field(default=None, repr=False)
    _loading_indices: set[int] = field(default_factory=set, repr=False)


_slideshow_sessions: dict[str, SlideshowSession] = {}
_refreshing_sessions: set[str] = set()  # inline_message_ids currently refreshing


def _build_keyboard(index: int, total: int) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    if index > 0:
        buttons.append(InlineKeyboardButton(text="◀️", callback_data="slide:prev"))
    buttons.append(
        InlineKeyboardButton(
            text=f"📸 {index + 1}/{total}", callback_data="slide:noop"
        )
    )
    if index < total - 1:
        buttons.append(InlineKeyboardButton(text="▶️", callback_data="slide:next"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _compress_url(source_link: str) -> str:
    """Compress a URL to fit within Telegram's 64-byte callback_data limit."""
    # For Instagram: extract clean URL (strips query params)
    ig_match = INSTAGRAM_URL_REGEX.search(source_link)
    if ig_match:
        url = ig_match.group(0)
    else:
        # For TikTok: strip query params and username (resolved by video ID)
        url = source_link.split("?")[0]
        url = re.sub(r"@[\w.]+", "@", url)

    # Strip protocol prefix
    url = re.sub(r"^https?://", "", url)
    return url


def _expand_url(compressed: str) -> str:
    """Expand a compressed URL back to a full URL."""
    return f"https://{compressed}"


def _build_expired_keyboard(
    index: int, total: int, source_link: str
) -> InlineKeyboardMarkup:
    """Build a keyboard with counter + refresh button for expired sessions."""
    compressed = _compress_url(source_link)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📸 {index + 1}/{total}",
                    callback_data="slide:noop",
                ),
                InlineKeyboardButton(
                    text="🔄",
                    callback_data=f"sr:{index}:{compressed}",
                ),
            ]
        ]
    )


async def _expire_session(inline_message_id: str) -> None:
    """Wait for TTL then remove session and show refresh button."""
    await asyncio.sleep(_SESSION_TTL)
    session = _slideshow_sessions.pop(inline_message_id, None)
    if session is None:
        return
    try:
        keyboard = _build_expired_keyboard(
            session.current_index,
            len(session.image_urls),
            session.source_link,
        )
        await bot.edit_message_reply_markup(
            inline_message_id=inline_message_id, reply_markup=keyboard
        )
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.debug(f"Failed to set slideshow refresh button: {e}")


def _reset_ttl(inline_message_id: str, session: SlideshowSession) -> None:
    if session._cleanup_task and not session._cleanup_task.done():
        session._cleanup_task.cancel()
    session._cleanup_task = asyncio.create_task(_expire_session(inline_message_id))


async def _upload_batch(
    pairs: list[tuple[int, bytes]],
    source_link: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> dict[int, str]:
    """Upload a list of (index, image_bytes) to storage. Returns index->file_id map."""
    file_ids: dict[int, str] = {}

    if len(pairs) == 1:
        # Media groups require 2+ items; upload individually
        idx, img_bytes = pairs[0]
        file_id = await upload_photo_to_storage(
            img_bytes, source_link, user_id, username, full_name
        )
        if file_id:
            file_ids[idx] = file_id
    else:
        caption = _build_storage_caption(source_link, user_id, username, full_name)
        media_group = [
            InputMediaPhoto(
                media=BufferedInputFile(img_bytes, f"slide_{idx}.jpg"),
                caption=caption if i == 0 else None,
                parse_mode="HTML" if i == 0 else None,
            )
            for i, (idx, img_bytes) in enumerate(pairs)
        ]
        messages = await bot.send_media_group(
            chat_id=STORAGE_CHANNEL_ID,
            media=media_group,
            disable_notification=True,
        )
        for (idx, _), msg in zip(pairs, messages):
            if msg.photo:
                file_ids[idx] = msg.photo[-1].file_id

    return file_ids


async def _download_and_upload_images(
    image_urls: list[str],
    source_link: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
    prepend: tuple[int, bytes] | None = None,
    client: TikTokClient | None = None,
    video_info: VideoInfo | None = None,
) -> dict[int, str]:
    """Download images, convert to native format, and upload in batches of 10.

    If client and video_info are provided (TikTok), uses robust proxy download
    for all images (prepend is ignored since all images are re-downloaded).
    Otherwise (Instagram/fallback), if prepend is given as (index, data),
    that image is included without re-downloading.
    Returns index->file_id map.
    """
    all_pairs: list[tuple[int, bytes]] = []

    if client and video_info and video_info._proxy_session:
        # TikTok: download all images via robust proxy path
        try:
            all_image_bytes = await client.download_slideshow_images(
                video_info, video_info._proxy_session
            )
        finally:
            video_info.close()
        for i, img_bytes in enumerate(all_image_bytes):
            data = await ensure_native_format(img_bytes)
            all_pairs.append((i, data))
    else:
        # Instagram / fallback: use prepend to avoid re-downloading
        start = prepend[0] + 1 if prepend else 0
        if prepend:
            all_pairs.append(prepend)
        urls_to_download = image_urls[start:]
        results = await asyncio.gather(
            *[_download_url(url) for url in urls_to_download],
            return_exceptions=True,
        )
        for i, result in enumerate(results, start=start):
            if isinstance(result, Exception) or result is None:
                logger.warning(f"Slideshow: failed to download image {i}")
                continue
            data = await ensure_native_format(result)
            all_pairs.append((i, data))

    file_ids: dict[int, str] = {}
    for batch_start in range(0, len(all_pairs), 10):
        batch = all_pairs[batch_start : batch_start + 10]
        batch_ids = await _upload_batch(
            batch, source_link, user_id, username, full_name
        )
        file_ids.update(batch_ids)
    return file_ids


async def register_slideshow(
    inline_message_id: str,
    image_urls: list[str],
    first_image_data: bytes,
    lang: str,
    source_link: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
    client: TikTokClient | None = None,
    video_info: VideoInfo | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Download all images, upload as galleries, create session, return (first_file_id, keyboard)."""
    file_ids = await _download_and_upload_images(
        image_urls, source_link, user_id, username, full_name,
        prepend=(0, first_image_data),
        client=client, video_info=video_info,
    )

    first_file_id = file_ids.get(0)
    if not first_file_id:
        raise ValueError(
            "Failed to upload first image to storage. "
            "Make sure STORAGE_CHANNEL_ID is configured in .env"
        )

    session = SlideshowSession(
        image_urls=image_urls,
        file_ids=file_ids,
        current_index=0,
        lang=lang,
        source_link=source_link,
        user_id=user_id,
        username=username,
        full_name=full_name,
    )
    _slideshow_sessions[inline_message_id] = session
    _reset_ttl(inline_message_id, session)
    return first_file_id, _build_keyboard(0, len(image_urls))


def cleanup_all_slideshows() -> None:
    """Cancel all TTL tasks (call on shutdown)."""
    for session in _slideshow_sessions.values():
        if session._cleanup_task and not session._cleanup_task.done():
            session._cleanup_task.cancel()
    _slideshow_sessions.clear()


@slideshow_router.callback_query(lambda cb: cb.data and cb.data.startswith("slide:"))
async def handle_slideshow_callback(callback: CallbackQuery) -> None:
    inline_message_id = callback.inline_message_id
    if not inline_message_id:
        await callback.answer()
        return

    session = _slideshow_sessions.get(inline_message_id)
    if session is None:
        await callback.answer("Slideshow expired.", show_alert=True)
        return

    action = callback.data.removeprefix("slide:")
    if action == "noop":
        await callback.answer()
        return

    total = len(session.image_urls)
    if action == "next":
        new_index = min(session.current_index + 1, total - 1)
    elif action == "prev":
        new_index = max(session.current_index - 1, 0)
    else:
        await callback.answer()
        return

    if new_index == session.current_index:
        await callback.answer()
        return

    # Guard against concurrent loads of the same index
    if new_index in session._loading_indices:
        await callback.answer("Loading…")
        return
    session._loading_indices.add(new_index)

    try:
        file_id = session.file_ids.get(new_index)
        if file_id is None:
            # Fallback: image failed during preload, try on-demand
            image_data = await _download_url(session.image_urls[new_index])
            if not image_data:
                await callback.answer("Failed to download image.", show_alert=True)
                return
            image_data = await ensure_native_format(image_data)
            file_id = await upload_photo_to_storage(
                image_data,
                session.source_link,
                session.user_id,
                session.username,
                session.full_name,
            )
            if not file_id:
                await callback.answer("Failed to upload image.", show_alert=True)
                return
            session.file_ids[new_index] = file_id

        session.current_index = new_index
        caption = result_caption(session.lang, session.source_link)
        media = InputMediaPhoto(media=file_id, caption=caption)
        keyboard = _build_keyboard(new_index, total)

        await bot.edit_message_media(
            inline_message_id=inline_message_id,
            media=media,
            reply_markup=keyboard,
        )
        _reset_ttl(inline_message_id, session)
        await callback.answer()
    except TelegramBadRequest as e:
        logger.debug(f"Slideshow edit failed: {e}")
        await callback.answer()
    except Exception as e:
        logger.error(f"Slideshow callback error: {e}")
        await callback.answer("Something went wrong.", show_alert=True)
    finally:
        session._loading_indices.discard(new_index)


@slideshow_router.callback_query(lambda cb: cb.data and cb.data.startswith("sr:"))
async def handle_slideshow_refresh(callback: CallbackQuery) -> None:
    inline_message_id = callback.inline_message_id
    if not inline_message_id:
        await callback.answer()
        return

    # Guard against concurrent refresh clicks
    if inline_message_id in _refreshing_sessions:
        await callback.answer("Refreshing…")
        return
    _refreshing_sessions.add(inline_message_id)

    # Parse "sr:{index}:{compressed_url}"
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        _refreshing_sessions.discard(inline_message_id)
        await callback.answer("Invalid refresh data.", show_alert=True)
        return

    try:
        saved_index = int(parts[1])
    except ValueError:
        _refreshing_sessions.discard(inline_message_id)
        await callback.answer("Invalid refresh data.", show_alert=True)
        return

    source_link = _expand_url(parts[2])

    user_id = callback.from_user.id
    username = callback.from_user.username
    full_name = callback.from_user.full_name
    tiktok_video_info: VideoInfo | None = None

    try:
        lang = await lang_func(user_id, callback.from_user.language_code)

        # Determine source and fetch images
        tiktok_client: TikTokClient | None = None

        if INSTAGRAM_URL_REGEX.search(source_link):
            ig_client = InstagramClient()
            media_info = await ig_client.get_media(source_link)
            image_urls = media_info.image_urls
        else:
            tiktok_client = TikTokClient(proxy_manager=ProxyManager.get_instance())
            tiktok_video_info = await tiktok_client.video(source_link)
            image_urls = tiktok_video_info.image_urls

        if not image_urls:
            await callback.answer("No images found.", show_alert=True)
            return

        file_ids = await _download_and_upload_images(
            image_urls, source_link, user_id, username, full_name,
            client=tiktok_client, video_info=tiktok_video_info,
        )

        if not file_ids:
            await callback.answer("Failed to download images.", show_alert=True)
            return

        # Clamp index to new total
        total = len(image_urls)
        index = max(0, min(saved_index, total - 1))

        file_id = file_ids.get(index)
        if file_id is None:
            # Fall back to first available
            for idx in sorted(file_ids):
                file_id = file_ids[idx]
                index = idx
                break
        if file_id is None:
            await callback.answer("Failed to upload images.", show_alert=True)
            return

        # Create new session
        session = SlideshowSession(
            image_urls=image_urls,
            file_ids=file_ids,
            current_index=index,
            lang=lang,
            source_link=source_link,
            user_id=user_id,
            username=username,
            full_name=full_name,
        )
        _slideshow_sessions[inline_message_id] = session

        # Edit message with refreshed image + nav keyboard
        caption = result_caption(lang, source_link)
        media = InputMediaPhoto(media=file_id, caption=caption)
        keyboard = _build_keyboard(index, total)

        await bot.edit_message_media(
            inline_message_id=inline_message_id,
            media=media,
            reply_markup=keyboard,
        )
        _reset_ttl(inline_message_id, session)
        await callback.answer()

    except TelegramBadRequest as e:
        logger.debug(f"Slideshow refresh edit failed: {e}")
        await callback.answer()
    except Exception as e:
        logger.error(f"Slideshow refresh error: {e}", exc_info=True)
        await callback.answer("Failed to refresh.", show_alert=True)
    finally:
        if tiktok_video_info:
            tiktok_video_info.close()
        _refreshing_sessions.discard(inline_message_id)
