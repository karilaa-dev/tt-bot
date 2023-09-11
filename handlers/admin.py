from io import BytesIO

from aiogram import types

from data.config import admin_ids, second_ids, bot_token
from data.loader import bot, cursor, dp
from misc.utils import backup_dp


@dp.message_handler(commands=['msg', 'tell', 'say', 'send'],
                    chat_type=types.ChatType.PRIVATE)
async def send_hi(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_ids:
        text = message.text.split(' ', 2)
        try:
            await bot.send_message(text[1], text[2])
            await message.answer('done')
        except:
            await message.answer('ops')


@dp.message_handler(commands=["export"], state='*')
async def export_users(message: types.Message):
    if message["from"]["id"] in admin_ids:
        users = cursor.execute('SELECT id FROM users').fetchall()
        users_result = ''
        for x in users:
            users_result += str(x[0]) + '\n'
        users_result = users_result.encode('utf-8')
        result_file = BytesIO(users_result)
        result_file.name = 'users.txt'
        await message.answer_document(result_file, caption='User list')


@dp.message_handler(commands=["backup"], state='*')
async def backup(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_ids:
        msg = await message.answer('<code>Backup started, please wait...</code>')
        await backup_dp(message.from_user.id)
        await msg.delete()
