import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, ReactionTypeEmoji

from data.config import locale, api_alt_mode, second_ids
from data.loader import dp, bot, cursor, sqlite
from misc.tiktok_api import ttapi
from misc.utils import lang_func, tCurrent, error_catch
from misc.video_types import send_music_result, music_button

music_router = Router(name=__name__)


@dp.callback_query(F.data.startswith('id'))
async def send_tiktok_sound(callback_query: CallbackQuery):
    # Vars
    call_msg = callback_query.message
    chat_id = call_msg.chat.id
    video_id = callback_query.data.lstrip('id/')
    status_message = False
    # Api init
    api = ttapi()
    # Group chat set
    group_chat = call_msg.chat.type != 'private'
    # Get chat language
    lang = lang_func(chat_id, callback_query.from_user.language_code)
    # Remove music button
    await call_msg.edit_reply_markup()
    try:  # If reaction is allowed, send it
        await call_msg.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
    except:
        status_message = await call_msg.reply('⏳', disable_notification=True)
    try:
        # Get music info
        if not api_alt_mode:
            music_info = await api.music(video_id)
        else:
            music_info = await api.rapid_music(video_id)
        if music_info in [None, False]:  # Return error if info is bad
            if not group_chat:  # Send error message, if not group chat
                if music_info is False:  # If api doesn't return info about video
                    await call_msg.reply(locale[lang]['bugged_error'])
                else:  # If something went wrong
                    await call_msg.reply(locale[lang]['error'])
            elif music_info is False:  # If api doesn't return info about video
                await call_msg.reply_markup(reply_markup=music_button(video_id, lang))
            return
        # Send upload action
        await bot.send_chat_action(chat_id, 'upload_document')
        if not group_chat:  # Send reaction if not group chat
            await call_msg.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
        # Generate caption
        await send_music_result(call_msg, music_info, lang, group_chat)
        if status_message:  # Remove status message if it exists
            await status_message.delete()
        else:  # Remove reaction otherwise
            await call_msg.react([])
        try:  # Try to write into database
            # Write into database
            cursor.execute('INSERT INTO music VALUES (?,?,?)',
                           (chat_id, tCurrent(), video_id))
            sqlite.commit()
            # Log music download
            logging.info(f'Music Download: CHAT {chat_id} - MUSIC {video_id}')
        except:
            # Log error
            logging.error('Cant write into database')
    except Exception as e:  # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if call_msg.chat.id in second_ids:
            await call_msg.reply('<code>{0}</code>'.format(error_text))
        try:
            await call_msg.edit_reply_markup(reply_markup=music_button(video_id, lang))
            if status_message:
                await status_message.delete()
            if not group_chat:
                await call_msg.reply(locale[lang]['error'])
                if not status_message:
                    await call_msg.react([ReactionTypeEmoji(emoji='😢')])
            else:
                if not status_message:
                    await call_msg.react([])
        except:
            pass
