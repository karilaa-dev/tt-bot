import logging

from aiogram import Router, F
from aiogram.types import Message, ReactionTypeEmoji, CallbackQuery

from data.config import locale, api_alt_mode, second_ids
from data.db_service import get_user_settings, add_video, should_show_ad
from data.loader import bot
from misc.adsgram import show_ad
from misc.tiktok_api import ttapi
from misc.utils import start_manager, error_catch, lang_func
from misc.video_types import send_video_result, send_image_result, image_ask_button

video_router = Router(name=__name__)


@video_router.message(F.text)
async def send_tiktok_video(message: Message):
    # Api init
    api = ttapi()
    # Statys message var
    status_message = False
    # Group chat set
    group_chat = message.chat.type != 'private'
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
                await message.reply(locale[lang]['link_error'])
            return
        try:  # If reaction is allowed, send it
            await message.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
        except:  # Send status message, if reaction is not allowed, and save it
            status_message = await message.reply('⏳', disable_notification=True)
        if api_alt_mode:
            video_info = await api.rapid_video(video_link)
        else:
            video_info = await api.video(video_link)
        if video_info in [None, False]:  # If video info is bad
            if status_message:  # Remove status message if it exists
                await status_message.delete()
            else:  # Send reaction if status message is not used
                await message.react([ReactionTypeEmoji(emoji='😢')])
            if not group_chat:  # Send error message, if not group chat
                if video_info is False:  # Send error message if request didn't return info about video
                    # if is_mobile:  # Send error message about shadowban if video link is mobile
                    #     await message.reply(locale[lang]['bugged_error_mobile'])
                    # else:  # Mention user error if video link is not mobile
                    await message.reply(locale[lang]['bugged_error'])
                else:  # Send error message if request is failed
                    await message.reply(locale[lang]['error'])
            return
        video_id = video_info['id']
        if not status_message:  # If status message is not used, send reaction
            try:
                await message.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
            except:
                pass
        if video_info['type'] == 'images':  # Process images, if video is images
            if len(video_info['data']) > 50:  # If images are more than 50, propose to download only last 10
                await message.reply(locale[lang]['to_much_images_warning'].format(video_link),
                                    reply_markup=image_ask_button(video_id, lang))
                return await message.react([])
            # Send upload image action
            await bot.send_chat_action(chat_id=message.chat.id, action='upload_photo')
            if group_chat:
                image_limit = 10
            else:
                image_limit = None
            was_processed = await send_image_result(message, video_info, lang, file_mode, image_limit)
        else:  # Process video, if video is video
            # Send upload video action
            await bot.send_chat_action(chat_id=message.chat.id, action='upload_video')
            # Send video
            try:
                await send_video_result(message, video_info, lang, file_mode, api_alt_mode)
            except:
                if not group_chat:
                    await message.reply(locale[lang]['error'])
                    if not status_message:
                        await message.react([ReactionTypeEmoji(emoji='😢')])
                else:
                    if not status_message:
                        await message.react([])
            was_processed = False  # Videos are not processed
        if status_message:
            await status_message.delete()
        else:
            await message.react([])
        # if not group_chat and await should_show_ad(message.chat.id):
        #     try:
        #         await show_ad(message.chat.id, lang)
        #     except Exception as e:
        #         if str(e) == "Banner not available":
        #             pass
        #         else:
        #             logging.error(f'Error while showing an ad: {e}')
        try:  # Try to write log into database
            # Write log into database
            await add_video(message.chat.id, video_link, video_info['type'] == 'images', was_processed)
            # Log into console
            logging.info(f'Video Download: CHAT {message.chat.id} - VIDEO {video_link}')
        # If cant write log into database or log into console
        except Exception as e:
            logging.error('Cant write into database')
            logging.error(e)
    except Exception as e:  # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if message.chat.id in second_ids:
            await message.reply('<code>{0}</code>'.format(error_text))
        try:
            if status_message:  # Remove status message if it exists
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


@video_router.callback_query(F.data.startswith('images/'))
async def send_images_custon(callback_query: CallbackQuery):
    # Api init
    api = ttapi()
    # Statys message var
    status_message = False
    # Get callback data
    data = callback_query.data.split('/')
    download_mode = data[1]
    video_id = int(data[2])
    # Get message info
    call_msg = callback_query.message
    group_chat = call_msg.chat.type != 'private'
    chat_id = call_msg.chat.id
    # Get chat db info
    settings = await get_user_settings(chat_id)
    if not settings:
        return
    lang, file_mode = settings
    # Remove buttons
    await call_msg.edit_reply_markup()
    try:  # If reaction is allowed, send it
        await call_msg.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
    except:
        status_message = await call_msg.reply('⏳', disable_notification=True)
    try:
        # Get video info
        video_info = await api.video(video_id)
        if video_info in [None, False]:  # Return error if info is bad
            if not group_chat:  # Send error message, if not group chat
                if video_info is False:  # If api doesn't return info about video
                    await call_msg.reply(locale[lang]['bugged_error_mobile'])
                else:  # If something went wrong
                    await call_msg.reply(locale[lang]['error'])
            elif video_info is False:  # If api doesn't return info about video
                await call_msg.reply_markup(reply_markup=image_ask_button(video_id, lang))
            return
        # Send upload action
        await bot.send_chat_action(chat_id=chat_id, action='upload_photo')
        if not group_chat:  # Send reaction if not group chat
            await call_msg.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
            image_limit = None
        else:
            image_limit = 10
        # Generate link
        link = f'https://www.tiktok.com/@{video_info["author"]}/video/{video_info["id"]}'
        # Set the link in video_info for the result_caption function
        video_info['link'] = link
        if download_mode == 'last10':  # Check download mode
            video_info['data'] = video_info['data'][-10:]
        # Send images
        was_processed = await send_image_result(call_msg, video_info, lang, file_mode, image_limit)
        if status_message:
            await status_message.delete()
        else:
            await call_msg.react([])
        try:  # Try to write log into database
            # Write log into database
            await add_video(chat_id, link, video_info['type'] == 'images', was_processed)
            # Log into console
            logging.info(f'Video Download: CHAT {chat_id} - VIDEO {link}')
            # If cant write log into database or log into console
        except Exception as e:
            logging.error('Cant write into database')
            logging.error(e)
    except Exception as e:  # If something went wrong
        error_text = error_catch(e)
        logging.error(error_text)
        if chat_id in second_ids:
            await call_msg.reply('<code>{0}</code>'.format(error_text))
        try:
            if status_message:  # Remove status message if it exists
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
