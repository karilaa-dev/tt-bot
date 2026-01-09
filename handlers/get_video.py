import logging

from aiogram import Router, F
from aiogram.types import Message, ReactionTypeEmoji, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale, second_ids, monetag_url
from data.db_service import (
    get_user_settings,
    add_video,
    should_show_ad,
    record_ad_show,
    increase_ad_count,
)
from data.loader import bot
from tiktok_api import TikTokClient, TikTokError
from misc.utils import start_manager, error_catch, lang_func
from misc.video_types import send_video_result, send_image_result, get_error_message

video_router = Router(name=__name__)


@video_router.message(F.text)
async def send_tiktok_video(message: Message):
    # Api init
    api = TikTokClient()
    # Statys message var
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

    try:
        # Check if link is valid
        video_link, is_mobile = await api.regex_check(message.text)
        # If not valid
        if video_link is None:
            # Send error message, if not in group chat
            if not group_chat:
                await message.reply(locale[lang]["link_error"])
            return
        try:  # If reaction is allowed, send it
            await message.react(
                [ReactionTypeEmoji(emoji="👀")], disable_notification=True
            )
        except:  # Send status message, if reaction is not allowed, and save it
            status_message = await message.reply("⏳", disable_notification=True)
        try:
            video_info = await api.video(video_link)
        except TikTokError as e:
            # Handle specific TikTok errors with appropriate messages
            if status_message:
                await status_message.delete()
            else:
                try:
                    await message.react([ReactionTypeEmoji(emoji="😢")])
                except:
                    pass
            if not group_chat:
                await message.reply(get_error_message(e, lang))
            return
        video_id = video_info.id
        if not status_message:  # If status message is not used, send reaction
            try:
                await message.react(
                    [ReactionTypeEmoji(emoji="👨‍💻")], disable_notification=True
                )
            except:
                pass
        if video_info.is_slideshow:  # Process images, if video is images
            # Send upload image action
            await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
            if group_chat:
                image_limit = 10
            else:
                image_limit = None
            was_processed = await send_image_result(
                message, video_info, lang, file_mode, image_limit
            )
        else:  # Process video, if video is video
            # Send upload video action
            await bot.send_chat_action(chat_id=message.chat.id, action="upload_video")
            # Send video
            try:
                await send_video_result(
                    message.chat.id,
                    video_info,
                    lang,
                    file_mode,
                    reply_to_message_id=message.message_id,
                )
            except:
                if not group_chat:
                    await message.reply(locale[lang]["error"])
                    if not status_message:
                        await message.react([ReactionTypeEmoji(emoji="😢")])
                else:
                    if not status_message:
                        await message.react([])
            was_processed = False  # Videos are not processed
        if not group_chat:
            try:
                if await should_show_ad(message.chat.id):
                    await record_ad_show(message.chat.id)
                    ad_button = InlineKeyboardBuilder()
                    ad_button.button(
                        text=locale[lang]["ad_support_button"], url=monetag_url
                    )
                    await message.answer(
                        locale[lang]["ad_support"], reply_markup=ad_button.as_markup()
                    )
                else:
                    await increase_ad_count(message.chat.id)
            except Exception as e:
                logging.error("Can't show ad")
                logging.error(e)
        if status_message:
            await status_message.delete()
        else:
            await message.react([])
        try:  # Try to write log into database
            # Write log into database
            await add_video(
                message.chat.id,
                video_link,
                video_info.is_slideshow,
                was_processed,
            )
            # Log into console
            logging.info(f"Video Download: CHAT {message.chat.id} - VIDEO {video_link}")
        # If cant write log into database or log into console
        except Exception as e:
            logging.error("Can't write into database")
            logging.error(e)
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
        except:
            pass
