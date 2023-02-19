from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from data.config import locale
from data.loader import dp, cursor, sqlite, bot
from misc.utils import lang_func

lang_keyboard = InlineKeyboardMarkup()
for lang_name in locale['langs']:
    lang_keyboard.add(InlineKeyboardButton(locale[lang_name]['lang_name'],
                                           callback_data=f'lang/{lang_name}'))


@dp.message_handler(commands=['lang'], state='*')
async def lang_change(message: types.Message):
    if message.chat.type != 'private':
        user_status = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if user_status.status not in ['creator', 'administrator']:
            lang = lang_func(message.chat.id, message['from']['language_code'])
            return await message.answer(locale[lang]['not_admin'])
    await message.answer('Select language:', reply_markup=lang_keyboard)


@dp.callback_query_handler(lambda call: call.data.startswith('lang'), state='*')
async def inline_lang(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    lang = callback_query.data.lstrip('lang/')
    if callback_query.message.chat.type != 'private':
        user_status = await bot.get_chat_member(chat_id, from_id)
        if user_status.status not in ['creator', 'administrator']:
            lang = lang_func(chat_id, callback_query['from']['language_code'])
            return await callback_query.answer(locale[lang]['not_admin'])
    try:
        cursor.execute('UPDATE users SET lang = ? WHERE id = ?',
                       (lang, chat_id))
        sqlite.commit()
        await bot.edit_message_text(locale[lang]['lang'], chat_id, msg_id)
    except:
        pass
    return await callback_query.answer()
