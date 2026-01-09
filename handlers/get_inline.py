from aiogram import Router
from aiogram.types import (
    InlineQuery, 
    ChosenInlineResult, 
    InlineQueryResultArticle, 
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultsButton
)

import logging

from data.config import locale
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings
from misc.tiktok_api import ttapi
from misc.video_types import send_video_result

inline_router = Router(name=__name__)

def please_wait_button(lang):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=locale[lang]['inline_download_video_wait'], callback_data=f"wait")
            ]
        ]
    )


@inline_router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    """Handle inline queries and return example results"""
    api = ttapi()
    query_text = inline_query.query.strip()
    user_id = inline_query.from_user.id
    lang = await lang_func(user_id, inline_query.from_user.language_code)
    user_info = await get_user(user_id)
    results = []

    if user_info is None:
        start_bot_button = InlineQueryResultsButton(
        text=locale[lang]['inline_start_bot'],
        start_parameter="inline")
        return await inline_query.answer(results, cache_time=0, button=start_bot_button, is_personal=True)
    
    if len(query_text) < 12:
        return await inline_query.answer(results, cache_time=0)

    video_link, is_mobile = await api.regex_check(query_text)
    if video_link is None:
        results.append(
            InlineQueryResultArticle(
                id="wrong_link",
                title=locale[lang]['inline_wrong_link_title'],
                description=locale[lang]['inline_wrong_link_description'],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]['inline_wrong_link'],
                    parse_mode="HTML"
                ),
                thumbnail_url="https://em-content.zobj.net/source/apple/419/cross-mark_274c.png"
            )
        )
        return await inline_query.answer(results, cache_time=0)
    else:
        results.append(
            InlineQueryResultArticle(
                id=f"download/{query_text}",
                title=locale[lang]['inline_download_video'],
                description=locale[lang]['inline_download_video_description'],
                input_message_content=InputTextMessageContent(
                    message_text=locale[lang]['inline_download_video_text']
                ),
                thumbnail_url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/tiktok-light.png",
                reply_markup=please_wait_button(lang)
            )
        )

    
    await inline_query.answer(results, cache_time=0)


@inline_router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult):
    """Handle when user selects an inline result"""
    api = ttapi()
    user_id = chosen_result.from_user.id
    message_id = chosen_result.inline_message_id
    video_link = chosen_result.query
    settings = await get_user_settings(user_id)
    was_processed = False
    if not settings:
        return
    lang, file_mode = settings

    try:
        video_info = await api.video(video_link)

        if video_info is False:
            return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['bugged_error'])
        elif video_info is None: 
            return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])
            
        if video_info['type'] == 'images':  # Process image
            return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['only_video_supported'])
            # await bot.edit_message_text(inline_message_id=message_id, text="⬆️ <code>Sending image...</code>\n\n")
            # try:
            #     was_processed = await send_image_result(message_id, video_info, lang, file_mode, 1)
            # except:
            #     await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])
        else:  # Process video
            await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['sending_inline_video'])
            # try:
            await send_video_result(message_id, video_info, lang, file_mode, True)
            # except:
            #     return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])

        try:  # Try to write log into database
            # Write log into database
            await add_video(user_id, video_link, video_info['type'] == 'images', was_processed, True)
            # Log into console
            logging.info(f'Video Download: INLINE {user_id} - VIDEO {video_link}')
        # If cant write log into database or log into console
        except Exception as e:
            logging.error('Cant write into database')
            logging.error(e)
    except Exception as e:  # If something went wrong
        logging.error(e)
        try:
            await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])
        except:
            pass
