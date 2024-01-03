import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, ReactionTypeEmoji
from httpx import AsyncClient, AsyncHTTPTransport

from data.config import locale
from data.loader import dp, bot, cursor, sqlite
from misc.tiktok_api import ttapi
from misc.utils import lang_func, tCurrent

music_router = Router(name=__name__)


@dp.callback_query(F.data.startswith('id'))
async def send_tiktok_sound(callback_query: CallbackQuery):
    # Api init
    api = ttapi()
    # Group chat set
    group_chat = callback_query.message.chat.type != 'private'
    # Vars for QoF
    chat_id = callback_query.message.chat.id
    msg_id = callback_query.message.message_id
    video_id = callback_query.data.lstrip('id/')
    # Get chat language
    lang = lang_func(chat_id, callback_query.from_user.language_code)
    # Send status reaction
    await callback_query.message.react([ReactionTypeEmoji(emoji='👀')], disable_notification=True)
    try:
        # Get music info
        playAddr = await api.music(int(video_id))
        # Return error if info is bad
        if playAddr in [None, False]:
            raise
        # Send reaction and upload action
        await bot.send_chat_action(chat_id, 'upload_document')
        await callback_query.message.react([ReactionTypeEmoji(emoji='👨‍💻')], disable_notification=True)
        # Generate caption
        caption = locale[lang]['result_song'].format(locale[lang]['bot_tag'],
                                                     playAddr['cover'])
        # Download music and cover
        async with AsyncClient(transport=AsyncHTTPTransport(retries=2)) as client:
            audio_request = await client.get(playAddr['data'], follow_redirects=True)
            cover_request = await client.get(playAddr['cover'], follow_redirects=True)
        # Buffer music and cover
        audio = BufferedInputFile(audio_request.content, f'{video_id}.mp3')
        cover = BufferedInputFile(cover_request.content, f'{video_id}.jpg')
        # Send music
        await bot.send_audio(chat_id, audio, reply_to_message_id=msg_id,
                             message_thread_id=callback_query.message.message_thread_id,
                             caption=caption, title=playAddr['title'],
                             performer=playAddr['author'],
                             duration=playAddr['duration'], thumbnail=cover,
                             disable_notification=group_chat)
        # Remove music button and reaction
        await callback_query.message.edit_reply_markup()
        await callback_query.message.react([], disable_notification=True)
        # Try to write into database
        try:
            # Write into database
            cursor.execute('INSERT INTO music VALUES (?,?,?)',
                           (chat_id, tCurrent(), video_id))
            sqlite.commit()
            # Log music download
            logging.info(f'Music Download: CHAT {chat_id} - MUSIC {video_id}')
        except:
            # Log error
            logging.error('Cant write into database')
    # If something went wrong
    except:
        try:
            await CallbackQuery.message.react([ReactionTypeEmoji(emoji='😢')], disable_notification=True)
        except:
            pass
        if not group_chat:
            await bot.send_message(chat_id, locale[lang]['error'], reply_to_message_id=msg_id)
    return await callback_query.answer()
