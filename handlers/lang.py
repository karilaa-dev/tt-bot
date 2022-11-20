from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from data.loader import dp, cursor, sqlite, bot
from data.config import locale

lang_keyboard = InlineKeyboardMarkup()
for lang_name in locale['langs']:
    lang_keyboard.add(InlineKeyboardButton(locale[lang_name]['lang_name'],
                                           callback_data=f'lang/{lang_name}'))


@dp.message_handler(commands=['lang'], chat_type=types.ChatType.PRIVATE,
                    state='*')
async def lang_change(message: types.Message):
    if message.chat.type == 'private':
        await message.answer('Select language:', reply_markup=lang_keyboard)


@dp.callback_query_handler(lambda call: call.data.startswith('lang'), state='*')
async def inline_lang(callback_query: types.CallbackQuery):
    cht_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    lang = callback_query.data.lstrip('lang/')
    try:
        cursor.execute('UPDATE users SET lang = ? WHERE id = ?',
                       (lang, from_id))
        sqlite.commit()
        await bot.edit_message_text(locale[lang]['lang'], cht_id, msg_id)
    except:
        pass
    return await callback_query.answer()
