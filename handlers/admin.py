from aiogram import types, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from data.loader import bot, cursor
from misc.utils import backup_dp, IsSecondAdmin

admin_router = Router(name=__name__)


@admin_router.message(Command('msg', 'tell', 'say', 'send'), IsSecondAdmin())
async def send_hi(message: types.Message):
    text = message.text.split(' ', 2)
    try:
        await bot.send_message(text[1], text[2])
        await message.answer('Message sent')
    except:
        await message.answer('ops')


@admin_router.message(Command('export'), IsSecondAdmin())
async def export_users(message: types.Message):
    users = cursor.execute('SELECT id FROM users').fetchall()
    users_result = ''
    for x in users:
        users_result += str(x[0]) + '\n'
    users_result = users_result.encode('utf-8')
    await message.answer_document(BufferedInputFile(users_result, 'users.txt'), caption='User list')


@admin_router.message(Command('backup'), IsSecondAdmin())
async def backup(message: types.Message):
    msg = await message.answer('<code>Backup started, please wait...</code>')
    await backup_dp(message.from_user.id)
    await msg.delete()
