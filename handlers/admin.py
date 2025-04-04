from aiogram import F
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from data.db_service import get_user_ids
from data.loader import bot
from misc.utils import backup_dp, IsSecondAdmin

admin_router = Router(name=__name__)


@admin_router.message(Command('msg', 'tell', 'say', 'send'), F.chat.type == 'private', IsSecondAdmin())
async def send_hi(message: Message):
    text = message.text.split(' ', 2)
    try:
        await bot.send_message(chat_id=text[1], text=text[2])
        await message.answer('Message sent')
    except:
        await message.answer('ops')


@admin_router.message(Command('export'), F.chat.type == 'private', IsSecondAdmin())
async def export_users(message: Message):
    users = await get_user_ids(only_positive=False)
    users_result = '\n'.join(str(user_id) for user_id in users)
    users_result = users_result.encode('utf-8')
    await message.answer_document(BufferedInputFile(users_result, 'users.txt'), caption='User list')


@admin_router.message(Command('backup'), F.chat.type == 'private', IsSecondAdmin())
async def backup(message: Message):
    msg = await message.answer('<code>Backup started, please wait...</code>')
    await backup_dp(message.chat.id)
    await msg.delete()
