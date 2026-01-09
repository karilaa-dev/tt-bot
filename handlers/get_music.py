import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, ReactionTypeEmoji

from data.config import locale, second_ids
from data.db_service import add_music
from data.loader import dp, bot
from tiktok_api import TikTokClient, TikTokError
from misc.utils import lang_func, error_catch
from misc.video_types import send_music_result, music_button, get_error_message

music_router = Router(name=__name__)


@dp.callback_query(F.data.startswith("id"))
async def send_tiktok_sound(callback_query: CallbackQuery):
    # Vars
    call_msg = callback_query.message
    chat_id = call_msg.chat.id
    video_id = callback_query.data.lstrip("id/")
    status_message = False
    # Api init
    api = TikTokClient()
    # Group chat set
    group_chat = call_msg.chat.type != "private"
    # Get chat language
    lang = await lang_func(chat_id, callback_query.from_user.language_code)
    # Remove music button
    await call_msg.edit_reply_markup()
    try:  # If reaction is allowed, send it
        await call_msg.react([ReactionTypeEmoji(emoji="👀")], disable_notification=True)
    except:
        status_message = await call_msg.reply("⏳", disable_notification=True)
    try:
        # Get music info
        music_info = await api.music(video_id)
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
            except:
                pass
        else:
            try:
                await call_msg.react([ReactionTypeEmoji(emoji="😢")])
            except:
                pass
        if not group_chat:
            await call_msg.reply(get_error_message(e, lang))
        try:
            await call_msg.edit_reply_markup(reply_markup=music_button(video_id, lang))
        except:
            pass
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
        except:
            pass
