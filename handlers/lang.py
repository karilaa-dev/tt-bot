from aiogram import F
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale
from data.db_service import update_user_lang
from data.loader import bot
from misc.utils import lang_func

lang_keyboard = InlineKeyboardBuilder()
for lang_name in locale['langs']:
    lang_keyboard.button(text=locale[lang_name]['lang_name'], callback_data=f'lang/{lang_name}')
lang_keyboard.adjust(2)
lang_keyboard = lang_keyboard.as_markup()

lang_router = Router(name=__name__)


@lang_router.message(Command('lang'))
async def lang_change(message: Message):
    if message.chat.type != 'private':
        user_status = await bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        if user_status.status not in ['creator', 'administrator']:
            lang = await lang_func(message.chat.id, message.from_user.language_code)
            return await message.answer(locale[lang]['not_admin'])
    await message.answer('Select language:', reply_markup=lang_keyboard)


@lang_router.callback_query(F.data.startswith('lang'))
async def inline_lang(callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    from_id = callback_query.from_user.id
    msg_id = callback_query.message.message_id
    lang = callback_query.data.lstrip('lang/')
    if callback_query.message.chat.type != 'private':
        user_status = await bot.get_chat_member(chat_id=chat_id, user_id=from_id)
        if user_status.status not in ['creator', 'administrator']:
            lang = await lang_func(chat_id, callback_query.from_user.language_code)
            return await callback_query.answer(locale[lang]['not_admin'])
    try:
        await update_user_lang(chat_id, lang)
        await bot.edit_message_text(text=locale[lang]['lang'], chat_id=chat_id, message_id=msg_id)
    except:
        pass
    return await callback_query.answer()
