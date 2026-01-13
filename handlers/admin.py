import logging

from aiogram import F
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import Message
from stats.botstat import Botstat

from data.loader import bot
from misc.utils import IsSecondAdmin, IsAdmin, get_users_file

admin_router = Router(name=__name__)


@admin_router.message(
    Command("msg", "tell", "say", "send"), F.chat.type == "private", IsSecondAdmin()
)
async def send_hi(message: Message):
    text = message.text.split(" ", 2)
    try:
        await bot.send_message(chat_id=text[1], text=text[2])
        await message.answer("Message sent")
    except TelegramForbiddenError:
        await message.answer("User has blocked the bot")
    except TelegramBadRequest as e:
        await message.answer(f"Bad request: {e}")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")
        await message.answer("ops")


@admin_router.message(Command("export"), F.chat.type == "private", IsSecondAdmin())
async def export_users(message: Message):
    users_file = await get_users_file()
    await message.answer_document(users_file, caption="User list")


@admin_router.message(Command("botstat"), F.chat.type == "private", IsAdmin())
async def botstat(message: Message):
    try:
        botstat = Botstat()
        await botstat.start_task()
        await message.answer("BotSafe stats verification started")
    except Exception as e:
        await message.answer(
            f"BotSafe stats verification unsuccessful: <code>{str(e)}</code>"
        )
