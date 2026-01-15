import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, ReactionTypeEmoji

from data.config import locale, second_ids, config
from data.db_service import add_music
from data.loader import bot
from tiktok_api import TikTokClient, TikTokError, ProxyManager
from misc.utils import lang_func, error_catch
from misc.video_types import send_music_result, music_button, get_error_message

music_router = Router(name=__name__)

# Retry emoji sequence for music download
RETRY_EMOJIS = ["👀", "🤔", "🙏"]


@music_router.callback_query(F.data.startswith("id"))
async def send_tiktok_sound(callback_query: CallbackQuery):
    # Vars
    call_msg = callback_query.message
    chat_id = call_msg.chat.id
    video_id = callback_query.data.lstrip("id/")
    status_message = None
    # Api init with proxy support
    api = TikTokClient(
        proxy_manager=ProxyManager.get_instance(),
        data_only_proxy=config["proxy"]["data_only"],
    )
    # Group chat set
    group_chat = call_msg.chat.type != "private"
    # Get chat language
    lang = await lang_func(chat_id, callback_query.from_user.language_code)
    # Remove music button (ignore if already removed - handles double-clicks)
    try:
        await call_msg.edit_reply_markup()
    except TelegramBadRequest:
        logging.debug("Music button already removed (double-click)")

    # Try to send initial reaction to show processing started
    try:
        await call_msg.react(
            [ReactionTypeEmoji(emoji=RETRY_EMOJIS[0])], disable_notification=True
        )
    except TelegramBadRequest:
        logging.debug("Reactions not allowed, falling back to status message")
        status_message = await call_msg.reply("⏳", disable_notification=True)

    try:
        # Get music info using 2-part retry strategy
        # Part 2: Music info extraction (retry with proxy rotation)
        # Part 3: Music download (retry with proxy rotation)
        music_info = await api.music(int(video_id))
        # Send upload action
        await bot.send_chat_action(chat_id=chat_id, action="upload_document")
        if not group_chat:  # Send reaction if not group chat
            await call_msg.react(
                [ReactionTypeEmoji(emoji="👨‍💻")], disable_notification=True
            )
        # Generate caption
        await send_music_result(call_msg, music_info, lang, group_chat)
        if status_message:  # Remove status message if it exists
            await status_message.delete()
        else:  # Remove reaction otherwise
            await call_msg.react([])
        try:  # Try to write into database
            # Write into database
            await add_music(chat_id, int(video_id))
            # Log music download
            logging.info(f"Music Download: CHAT {chat_id} - MUSIC {video_id}")
        except Exception as e:
            logging.error("Cant write into database")
            logging.error(e)
    except TikTokError as e:
        # Handle specific TikTok errors with appropriate messages
        if status_message:
            try:
                await status_message.delete()
            except TelegramBadRequest:
                logging.debug("Status message already deleted")
        else:
            try:
                await call_msg.react([ReactionTypeEmoji(emoji="😢")])
            except TelegramBadRequest:
                logging.debug("Failed to set error reaction")
        if not group_chat:
            await call_msg.reply(get_error_message(e, lang))
        try:
            await call_msg.edit_reply_markup(reply_markup=music_button(video_id, lang))
        except TelegramBadRequest:
            logging.debug("Failed to restore music button")
    except Exception as e:  # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if call_msg.chat.id in second_ids:
            await call_msg.reply("<code>{0}</code>".format(error_text))
        try:
            await call_msg.edit_reply_markup(reply_markup=music_button(video_id, lang))
            if status_message:
                await status_message.delete()
            if not group_chat:
                await call_msg.reply(locale[lang]["error"])
                if not status_message:
                    await call_msg.react([ReactionTypeEmoji(emoji="😢")])
            else:
                if not status_message:
                    await call_msg.react([])
        except TelegramBadRequest:
            logging.debug("Failed to update UI during error cleanup")
        except Exception as cleanup_err:
            logging.warning(f"Unexpected error during cleanup: {cleanup_err}")
