import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReactionTypeEmoji, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale, second_ids, monetag_url, config
from data.db_service import (
    get_user_settings,
    add_video,
    should_show_ad,
    record_ad_show,
    increase_ad_count,
)
from data.loader import bot
from tiktok_api import TikTokClient, TikTokError, ProxyManager
from misc.queue_manager import QueueManager
from misc.utils import start_manager, error_catch, lang_func
from misc.video_types import send_video_result, send_image_result, get_error_message

video_router = Router(name=__name__)

# Retry emoji sequence: shown for each attempt
# Note: Must use valid Telegram reaction emojis (🔄 and ⏳ are not valid)
RETRY_EMOJIS = ["👀", "🤔", "🙏"]

# Callback data prefix for retry button
RETRY_CALLBACK_PREFIX = "retry_video"


def try_again_button(lang: str):
    """Create a 'Try Again' button for queue full error."""
    keyb = InlineKeyboardBuilder()
    keyb.button(
        text=locale[lang]["try_again_button"],
        callback_data=RETRY_CALLBACK_PREFIX,
    )
    return keyb.as_markup()


@video_router.message(F.text)
async def send_tiktok_video(message: Message):
    # Api init with proxy support
    api = TikTokClient(
        proxy_manager=ProxyManager.get_instance(),
        data_only_proxy=config["proxy"]["data_only"],
    )
    # Status message var
    status_message = False
    # Group chat set
    group_chat = message.chat.type != "private"
    # Get chat db info
    settings = await get_user_settings(message.chat.id)
    if not settings:  # Add new user if not in DB
        # Set lang and file mode for new chat
        lang = await lang_func(message.chat.id, message.from_user.language_code, True)
        file_mode = False
        # Start new chat manager
        await start_manager(message.chat.id, message, lang)
    else:  # Set lang and file mode if in DB
        lang, file_mode = settings

    # Get queue manager and queue config
    queue = QueueManager.get_instance()
    queue_config = config["queue"]

    try:
        # Check if link is valid (quick regex check before any network calls)
        video_link, is_mobile = await api.regex_check(message.text)
        # If not valid
        if video_link is None:
            # Send error message, if not in group chat
            if not group_chat:
                await message.reply(locale[lang]["link_error"])
            return

        # Check per-user queue limit before proceeding (0 = no limit)
        max_queue = queue_config["max_user_queue_size"]
        if max_queue > 0:
            user_queue_count = queue.get_user_queue_count(message.chat.id)
            if user_queue_count >= max_queue:
                if not group_chat:
                    await message.reply(
                        locale[lang]["error_queue_full"].format(user_queue_count),
                        reply_markup=try_again_button(lang),
                    )
                return

        # Try to send initial reaction to show processing started
        try:
            await message.react(
                [ReactionTypeEmoji(emoji=RETRY_EMOJIS[0])], disable_notification=True
            )
        except TelegramBadRequest:
            logging.debug("Reactions not allowed, falling back to status message")
            # Send status message if reaction is not allowed
            status_message = await message.reply("⏳", disable_notification=True)

        # Acquire info queue slot with per-user limit
        async with queue.info_queue(message.chat.id) as acquired:
            if not acquired:
                # User limit exceeded (shouldn't happen due to pre-check, but handle anyway)
                if status_message:
                    await status_message.delete()
                if not group_chat:
                    await message.reply(
                        locale[lang]["error_queue_full"].format(
                            queue.get_user_queue_count(message.chat.id)
                        ),
                        reply_markup=try_again_button(lang),
                    )
                return

            try:
                # Fetch video info using 3-part retry strategy
                # Part 1: URL resolution (retry with proxy rotation)
                # Part 2: Video info extraction (retry with proxy rotation)
                # Part 3: Video download (retry with proxy rotation)
                # For slideshows, Part 3 happens later during image sending
                video_info = await api.video(video_link)
            except TikTokError as e:
                # Handle specific TikTok errors with appropriate messages
                if status_message:
                    await status_message.delete()
                else:
                    try:
                        await message.react([ReactionTypeEmoji(emoji="😢")])
                    except TelegramBadRequest:
                        logging.debug("Failed to set error reaction")
                if not group_chat:
                    await message.reply(get_error_message(e, lang))
                return

        # Successfully got video info - show processing emoji
        if not status_message:
            try:
                await message.react(
                    [ReactionTypeEmoji(emoji="👨‍💻")], disable_notification=True
                )
            except TelegramBadRequest:
                logging.debug("Failed to set processing reaction")

        # Use try/finally to ensure video_info resources are cleaned up
        # (especially download context for slideshows)
        try:
            # Send video/images (no global send queue - per-user limit only)
            if video_info.is_slideshow:  # Process images
                # Send upload image action
                await bot.send_chat_action(
                    chat_id=message.chat.id, action="upload_photo"
                )
                if group_chat:
                    image_limit = 10
                else:
                    image_limit = None
                was_processed = await send_image_result(
                    message, video_info, lang, file_mode, image_limit, client=api
                )
            else:  # Process video
                # Send upload video action
                await bot.send_chat_action(
                    chat_id=message.chat.id, action="upload_video"
                )
                # Send video
                try:
                    await send_video_result(
                        message.chat.id,
                        video_info,
                        lang,
                        file_mode,
                        reply_to_message_id=message.message_id,
                    )
                except TelegramBadRequest as e:
                    logging.warning(f"Failed to send video: {e}")
                    if not group_chat:
                        await message.reply(locale[lang]["error"])
                        if not status_message:
                            try:
                                await message.react([ReactionTypeEmoji(emoji="😢")])
                            except TelegramBadRequest:
                                pass
                    else:
                        if not status_message:
                            try:
                                await message.react([])
                            except TelegramBadRequest:
                                pass
                except Exception as e:
                    logging.error(f"Unexpected error sending video: {e}")
                    if not group_chat:
                        await message.reply(locale[lang]["error"])
                        if not status_message:
                            try:
                                await message.react([ReactionTypeEmoji(emoji="😢")])
                            except TelegramBadRequest:
                                pass
                    else:
                        if not status_message:
                            try:
                                await message.react([])
                            except TelegramBadRequest:
                                pass
                was_processed = False  # Videos are not processed

            # Show ad if applicable (only in private chats)
            if not group_chat:
                try:
                    if await should_show_ad(message.chat.id):
                        await record_ad_show(message.chat.id)
                        ad_button = InlineKeyboardBuilder()
                        ad_button.button(
                            text=locale[lang]["ad_support_button"], url=monetag_url
                        )
                        await message.answer(
                            locale[lang]["ad_support"],
                            reply_markup=ad_button.as_markup(),
                        )
                    else:
                        await increase_ad_count(message.chat.id)
                except Exception as e:
                    logging.error("Can't show ad")
                    logging.error(e)

            # Clean up status
            if status_message:
                await status_message.delete()
            else:
                await message.react([])

            # Log to database
            try:
                await add_video(
                    message.chat.id,
                    video_link,
                    video_info.is_slideshow,
                    was_processed,
                )
                logging.info(
                    f"Video Download: CHAT {message.chat.id} - VIDEO {video_link}"
                )
            except Exception as e:
                logging.error("Can't write into database")
                logging.error(e)
        finally:
            # Clean up video_info resources (closes YDL context for slideshows)
            video_info.close()

    except Exception as e:  # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if message.chat.id in second_ids:
            await message.reply("<code>{0}</code>".format(error_text))
        try:
            if status_message:  # Remove status message if it exists
                await status_message.delete()
            if not group_chat:
                await message.reply(locale[lang]["error"])
                if not status_message:
                    await message.react([ReactionTypeEmoji(emoji="😢")])
            else:
                if not status_message:
                    await message.react([])
        except TelegramBadRequest:
            logging.debug("Failed to update UI during error cleanup")
        except Exception as cleanup_err:
            logging.warning(f"Unexpected error during cleanup: {cleanup_err}")


@video_router.callback_query(F.data == RETRY_CALLBACK_PREFIX)
async def handle_retry_callback(callback: CallbackQuery):
    """Handle 'Try Again' button click for queue full error."""
    # Ensure callback.message exists and is accessible
    if not callback.message or not hasattr(callback.message, "reply_to_message"):
        await callback.answer("Message not accessible", show_alert=True)
        return

    # Get the original message that contains the TikTok link
    original_message = callback.message.reply_to_message

    if not original_message or not original_message.text:
        await callback.answer("Original message not found", show_alert=True)
        return

    # Delete the error message with the button
    try:
        if hasattr(callback.message, "delete"):
            await callback.message.delete()
    except TelegramBadRequest:
        logging.debug("Retry button message already deleted")

    # Answer the callback to remove loading state
    await callback.answer()

    # Re-process the original message
    await send_tiktok_video(original_message)
