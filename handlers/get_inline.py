import asyncio
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineQuery,
    ChosenInlineResult,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultsButton,
)

from data.config import locale, config
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings
from tiktok_api import TikTokClient, TikTokError
from misc.queue_manager import QueueManager
from misc.video_types import send_video_result, get_error_message

inline_router = Router(name=__name__)


def please_wait_button(lang):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=locale[lang]["inline_download_video_wait"],
                    callback_data=f"wait",
                )
            ]
        ]
    )


@inline_router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    """Handle inline queries and return example results"""
    api = TikTokClient()
    query_text = inline_query.query.strip()
    user_id = inline_query.from_user.id
    lang = await lang_func(user_id, inline_query.from_user.language_code)
    user_info = await get_user(user_id)
    results = []

    if user_info is None:
        start_bot_button = InlineQueryResultsButton(
            text=locale[lang]["inline_start_bot"], start_parameter="inline"
        )
        return await inline_query.answer(
            results, cache_time=0, button=start_bot_button, is_personal=True
        )

    if len(query_text) < 12:
        return await inline_query.answer(results, cache_time=0)

    video_link, is_mobile = await api.regex_check(query_text)
    if video_link is None:
        results.append(
            InlineQueryResultArticle(
                id="wrong_link",
                title=locale[lang]["inline_wrong_link_title"],
                description=locale[lang]["inline_wrong_link_description"],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]["inline_wrong_link"], parse_mode="HTML"
                ),
                thumbnail_url="https://em-content.zobj.net/source/apple/419/cross-mark_274c.png",
            )
        )
        return await inline_query.answer(results, cache_time=0)
    else:
        results.append(
            InlineQueryResultArticle(
                id=f"download/{query_text}",
                title=locale[lang]["inline_download_video"],
                description=locale[lang]["inline_download_video_description"],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]["inline_download_video_text"]
                ),
                thumbnail_url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/tiktok-light.png",
                reply_markup=please_wait_button(lang),
            )
        )

    await inline_query.answer(results, cache_time=0)


@inline_router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult):
    """Handle when user selects an inline result"""
    api = TikTokClient()
    user_id = chosen_result.from_user.id
    username = chosen_result.from_user.username
    full_name = chosen_result.from_user.full_name
    message_id = chosen_result.inline_message_id
    video_link = chosen_result.query
    settings = await get_user_settings(user_id)
    was_processed = False
    if not settings:
        return
    lang, file_mode = settings

    # Get queue manager and retry config
    queue = QueueManager.get_instance()
    retry_config = config["queue"]
    max_attempts = retry_config["retry_max_attempts"]

    # Define callback to update inline message on retry
    async def update_inline_status(attempt: int):
        """Update inline message text on each retry attempt."""
        # Don't show attempt count on first attempt
        if attempt == 1:
            return
        try:
            retry_text = locale[lang]["inline_retry_attempt"].format(
                attempt, max_attempts
            )
            await bot.edit_message_text(
                inline_message_id=message_id,
                text=f"{retry_text}\n\n{locale[lang]['inline_download_video_text']}",
            )
        except Exception as e:
            logging.debug(f"Failed to update inline retry status: {e}")
        # Brief delay to allow message update to register before retry
        await asyncio.sleep(0.5)

    try:
        # Use queue with bypass_user_limit=True for inline downloads
        # Inline downloads bypass the per-user queue limit
        async with queue.info_queue(user_id, bypass_user_limit=True) as acquired:
            if not acquired:
                # This shouldn't happen with bypass, but handle anyway
                await bot.edit_message_text(
                    inline_message_id=message_id, text=locale[lang]["error"]
                )
                return

            # Use video_with_retry for inline downloads too
            video_info = await api.video_with_retry(
                video_link,
                max_attempts=max_attempts,
                request_timeout=retry_config["retry_request_timeout"],
                on_retry=update_inline_status,
            )

        if video_info.is_slideshow:  # Process image
            return await bot.edit_message_text(
                inline_message_id=message_id, text=locale[lang]["only_video_supported"]
            )
        else:  # Process video
            await bot.edit_message_text(
                inline_message_id=message_id, text=locale[lang]["sending_inline_video"]
            )

            # Send video (no global send queue - per-user limit only)
            await send_video_result(
                message_id,
                video_info,
                lang,
                file_mode,
                inline_message=True,
                user_id=user_id,
                username=username,
                full_name=full_name,
            )

        try:  # Try to write log into database
            # Write log into database
            await add_video(
                user_id, video_link, video_info.is_slideshow, was_processed, True
            )
            # Log into console
            logging.info(f"Video Download: INLINE {user_id} - VIDEO {video_link}")
        # If cant write log into database or log into console
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)

    except TikTokError as e:
        # Handle specific TikTok errors with appropriate messages
        logging.error(f"TikTok error for inline {video_link}: {e}")
        try:
            await bot.edit_message_text(
                inline_message_id=message_id, text=get_error_message(e, lang)
            )
        except TelegramBadRequest:
            logging.debug("Failed to update inline error message")
        except Exception as err:
            logging.warning(f"Unexpected error updating inline message: {err}")
    except Exception as e:  # If something went wrong
        logging.error(e)
        try:
            await bot.edit_message_text(
                inline_message_id=message_id, text=locale[lang]["error"]
            )
        except TelegramBadRequest:
            logging.debug("Failed to update inline error message")
        except Exception as err:
            logging.warning(f"Unexpected error updating inline message: {err}")
