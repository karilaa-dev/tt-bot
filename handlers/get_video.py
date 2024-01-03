import logging

from aiogram import Router, F
from aiogram.types import Message, ReactionTypeEmoji

from data.config import locale
from data.loader import cursor, sqlite, bot
from misc.tiktok_api import ttapi
from misc.utils import tCurrent, start_manager
from misc.video_types import send_video_result, send_image_result

video_router = Router(name=__name__)


@video_router.message(F.text)
async def send_tiktok_video(message: Message):
    # Api init
    api = ttapi()
    # Group chat set
    group_chat = message.chat.type != 'private'
    #Get chat db info
    req = cursor.execute('SELECT lang, file_mode FROM users WHERE id = ?',
                         (message.chat.id,)).fetchone()
    #Start manager if not in DB
    if req is None:
        #Set lang and file mode for new chat
        lang, file_mode = message.from_user.language_code, False
        #Start new chat manager
        await start_manager(message.chat.id, message, lang)
    #Set lang and file mode if in DB
    else:
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
        #If valid, send reaction
        await message.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
        #Get video id
        video_id = await api.get_id(link, is_mobile)
        #If video id is bad, send reaction and error message
        if video_id is None:
            #Send reaction and error message, if not group chat
            if not group_chat:
                await message.react([ReactionTypeEmoji(emoji='😢')])
                await message.reply('Try creating new share link from tiktok, or you send a wrong link')#locale[lang]['link_error'])
            return
        #Get video info
        video_info = await api.video(video_id)
        #If video info is bad, send reaction and error message
        if video_info in [None, False]:
            #Send reaction and error message, if not group chat
            if not group_chat:
                #Send error message if request didn't return info about video
                if video_info is False:
                    if is_mobile:
                        await message.reply("Some bugged videos can't download from tiktok")#locale[lang]['link_error'])
                    else:
                        await message.reply("Some bugged videos can't download from tiktok, or you send a wrong link")
                #Send error message if request is failed
                else:
                    await message.reply(locale[lang]['error'])
            return
        #Send reaction and upload video action
        await bot.send_chat_action(message.chat.id, 'upload_video')
        await message.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
        #Process images, if video is images
        if video_info['type'] == 'images':
            if group_chat:
                image_limit = 10
            else:
                image_limit = None
            await send_image_result(message, video_info, lang, file_mode, link, image_limit)
        #Process video, if video is video
        else:
            await send_video_result(message, video_info, lang, file_mode, link)
        await message.react([ReactionTypeEmoji(emoji='👍')], disable_notification=True)
        #Try to write log into database
        try:
            # Write log into database
            cursor.execute(f'INSERT INTO videos VALUES (?,?,?,?)',
                           (message.chat.id, tCurrent(), link, video_info['type'] == 'images'))
            sqlite.commit()
            # Log into console
            logging.info(f'Video Download: CHAT {message.chat.id} - VIDEO {link}')
        # If cant write log into database or log into console
        except:
            logging.error('Cant write into database')
    # If something went wrong
    except:
        try:
            await message.react([ReactionTypeEmoji(emoji='😢')])
        except:
            pass
        if not group_chat:
            await message.reply(locale[lang]['error'])
        return
