import logging

from aiogram import Router, F
from aiogram.types import Message, ReactionTypeEmoji

from data.config import locale, admin_ids
from data.loader import cursor, sqlite, bot
from misc.tiktok_api import ttapi
from misc.utils import tCurrent, start_manager, error_catch, lang_func
from misc.video_types import send_video_result, send_image_result

video_router = Router(name=__name__)


@video_router.message(F.text)
async def send_tiktok_video(message: Message):
    # Api init
    api = ttapi()
    # Statys message var
    status_message = False
    # Group chat set
    group_chat = message.chat.type != 'private'
    #Get chat db info
    req = cursor.execute('SELECT lang, file_mode FROM users WHERE id = ?',
                         (message.chat.id,)).fetchone()
    if req is None: #Add new user if not in DB
        # Set lang and file mode for new chat
        lang = lang_func(message.chat.id, message.from_user.language_code, True)
        file_mode = False
        #Start new chat manager
        await start_manager(message.chat.id, message, lang)
    else: #Set lang and file mode if in DB
        lang, file_mode = req[0], bool(req[1])

    try:
        #Check if link is valid
        link, is_mobile = await api.regex_check(message.text)
        #If not valid
        if link is None:
            #Send error message, if not in group chat
            if not group_chat:
                await message.reply(locale[lang]['link_error'])
            return
        try: # If reaction is allowed, send it
            await message.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
        except: # Send status message, if reaction is not allowed, and save it
            status_message = await message.reply('⏳', disable_notification=True)
        #Get video id
        video_id = await api.get_id(link, is_mobile)
        if video_id is None: #If video id is bad, send reaction and error message
            if status_message: # Remove status message if it exists
                await status_message.delete()
            else: # Send reaction if status message is not used
                await message.react([ReactionTypeEmoji(emoji='😢')])
            if not group_chat: # Send error message, if not group chat
                await message.reply(locale[lang]['bad_generated_link'])
            return
        #Get video info
        video_info = await api.video(video_id)
        if video_info in [None, False]: #If video info is bad
            if status_message: # Remove status message if it exists
                await status_message.delete()
            else: # Send reaction if status message is not used
                await message.react([ReactionTypeEmoji(emoji='😢')])
            if not group_chat: #Send error message, if not group chat
                if video_info is False: #Send error message if request didn't return info about video
                    if is_mobile: # Send error message about shadowban if video link is mobile
                        await message.reply(locale[lang]['bugged_error_mobile'])
                    else: # Mention user error if video link is not mobile
                        await message.reply(locale[lang]['bugged_error'])
                else: #Send error message if request is failed
                    await message.reply(locale[lang]['error'])
            return
        #Send reaction and upload video action
        await bot.send_chat_action(message.chat.id, 'upload_video')
        if not status_message: # If status message is not used, send reaction
            try:
                await message.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
            except:
                pass
        if video_info['type'] == 'images': # Process images, if video is images
            if group_chat:
                image_limit = 10
            else:
                image_limit = None
            await send_image_result(message, video_info, lang, file_mode, link, image_limit)
        else: #Process video, if video is video
            await send_video_result(message, video_info, lang, file_mode, link)
        if status_message:
            await status_message.delete()
        else:
            await message.react([])
        try: #Try to write log into database
            # Write log into database
            cursor.execute(f'INSERT INTO videos VALUES (?,?,?,?)',
                           (message.chat.id, tCurrent(), link, video_info['type'] == 'images'))
            sqlite.commit()
            # Log into console
            logging.info(f'Video Download: CHAT {message.chat.id} - VIDEO {link}')
        # If cant write log into database or log into console
        except:
            logging.error('Cant write into database')
    except Exception as e: # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if message.chat.id in admin_ids:
            await message.reply('<code>{0}</code>'.format(error_text))
        try:
            if status_message: # Remove status message if it exists
                await status_message.delete()
            if not group_chat:
                await message.reply(locale[lang]['error'])
                if not status_message:
                    await message.react([ReactionTypeEmoji(emoji='😢')])
            else:
                if not status_message:
                    await message.react([])
        except:
            pass
