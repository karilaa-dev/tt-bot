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

from data.config import locale, api_alt_mode
from data.loader import bot
from misc.utils import lang_func
from data.db_service import add_video, get_user, get_user_settings, increment_ad_msgs
from misc.tiktok_api import ttapi
from misc.video_types import send_video_result, send_image_result, image_ask_button

inline_router = Router(name=__name__)


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
        text="Start Bot to use inline download",
        start_parameter="inline")
        return await inline_query.answer(results, cache_time=0, button=start_bot_button, is_personal=True)
    
    if len(query_text) < 12:
        return await inline_query.answer(results, cache_time=0)

    video_link, is_mobile = await api.regex_check(query_text)
    if video_link is None:
        results.append(
            InlineQueryResultArticle(
                id="wrong_link",
                title="Link is not valid",
                description="Please enter a valid TikTok link",
                input_message_content=InputTextMessageContent(
                    message_text="🔍 <b>Link is not valid</b>\n\n"
                               "Please enter a valid TikTok link",
                    parse_mode="HTML"
                ),
                thumbnail_url="https://em-content.zobj.net/source/apple/419/cross-mark_274c.png"
            )
        )
        return await inline_query.answer(results, cache_time=0)
    results.append(
        InlineQueryResultArticle(
            id=f"download/{query_text}",
            title="🎬 Download Video",
            description="Download TikTok videos without watermark",
            input_message_content=InputTextMessageContent(
                message_text="🎬 <b>Downloading video...</b>\n\n"
                           "Please wait while we process your request."
            ),
            thumbnail_url="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/tiktok-light.png", reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Please wait...", callback_data=f"wait")
                    ]
                ]
            )
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
    
    if not settings:
        return
    lang, file_mode = settings
    #await bot.edit_message_text(inline_message_id=message_id, text="🎬 <b>Test</b>\n\n"
    #                      "Please wait while we process your request.")

    try:
        if api_alt_mode:
            video_info = await api.rapid_video(video_link)
        else:
            video_info = await api.video(video_link)

        if video_info is False:
            return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['bugged_error'])
        elif video_info is None: 
            return await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])
            
        video_id = video_info['id']
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
            await bot.edit_message_text(inline_message_id=message_id, text="⬆️ <code>Sending video...</code>\n\n")
            # Send video
            try:
                await send_video_result(message_id, video_info, lang, file_mode, api_alt_mode, True)
            except:
                await bot.edit_message_text(inline_message_id=message_id, text=locale[lang]['error'])
            was_processed = False  # Videos are not processed

        await increment_ad_msgs(user_id)

        try:  # Try to write log into database
            # Write log into database
            await add_video(user_id, video_link, video_info['type'] == 'images', was_processed)
            # Log into console
            logging.info(f'Video Download: CHAT {user_id} - VIDEO {video_link}')
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
