import asyncio
import logging
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
from media_types.http_session import _download_url
from media_types.image_processing import ensure_native_format
from media_types.storage import (
    STORAGE_CHANNEL_ID,
    _build_storage_caption,
    upload_photo_to_storage,
)
from media_types.ui import result_caption

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


async def _expire_session(inline_message_id: str) -> None:
    """Wait for TTL then remove session and strip buttons."""
    await asyncio.sleep(_SESSION_TTL)
    session = _slideshow_sessions.pop(inline_message_id, None)
    if session is None:
        return
    try:
        await bot.edit_message_reply_markup(
            inline_message_id=inline_message_id, reply_markup=None
        )
    except TelegramBadRequest:
        pass
    except Exception as e:
        logger.debug(f"Failed to remove slideshow buttons: {e}")


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


async def register_slideshow(
    inline_message_id: str,
    image_urls: list[str],
    first_image_data: bytes,
    lang: str,
    source_link: str,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Download all images, upload as galleries, create session, return (first_file_id, keyboard)."""
    # Download remaining images concurrently
    download_tasks = [_download_url(url) for url in image_urls[1:]]
    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    # Build full list: index 0 already has data, rest from downloads
    all_pairs: list[tuple[int, bytes]] = [(0, first_image_data)]
    for i, result in enumerate(results, start=1):
        if isinstance(result, Exception) or result is None:
            logger.warning(f"Slideshow: failed to download image {i}")
            continue
        data = await ensure_native_format(result)
        all_pairs.append((i, data))

    # Upload in batches of 10 as media groups
    file_ids: dict[int, str] = {}
    for batch_start in range(0, len(all_pairs), 10):
        batch = all_pairs[batch_start : batch_start + 10]
        batch_ids = await _upload_batch(
            batch, source_link, user_id, username, full_name
        )
        file_ids.update(batch_ids)

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
