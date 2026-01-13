import logging
from asyncio import sleep
from copy import copy

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from data.db_service import get_user_ids
from misc.utils import IsAdmin

advert_router = Router(name=__name__)

advert_message: Message = None

admin_keyboard = ReplyKeyboardBuilder()
admin_keyboard.button(text="👁‍🗨Check message")
admin_keyboard.button(text="✏Edit message")
admin_keyboard.button(text="📢Send message")
admin_keyboard.button(text="🔽Hide keyboard")
admin_keyboard.adjust(2, 1, 1)
admin_keyboard = admin_keyboard.as_markup(resize_keyboard=True)

back_keyboard = ReplyKeyboardBuilder()
back_keyboard.button(text="↩Return")
back_keyboard = back_keyboard.as_markup(resize_keyboard=True)


class AdminMenu(StatesGroup):
    menu = State()
    add = State()


@advert_router.message(F.text == "↩Return")
@advert_router.message(Command("stop", "cancel", "back"))
async def cancel(message: Message, state: FSMContext):
    await message.answer("↩You have returned", reply_markup=admin_keyboard)
    await state.clear()


@advert_router.message(F.text == "🔽Hide keyboard")
@advert_router.message(Command("hide"))
async def send_clear_keyboard(message: Message):
    await message.answer(
        "🔽You successfully hide the keyboard", reply_markup=ReplyKeyboardRemove()
    )


@advert_router.message(Command("admin"), IsAdmin(), F.chat.type == "private")
async def send_admin(message: Message):
    await message.answer("🤖You opened admin menu", reply_markup=admin_keyboard)


@advert_router.message(F.text == "👁‍🗨Check message", IsAdmin())
async def adb_check(message: Message):
    if advert_message is not None:
        await advert_message.send_copy(message.from_user.id)
    else:
        await message.answer("⚠️You have not created a message yet")


@advert_router.message(F.text == "📢Send message", IsAdmin())
async def adv_go(message: Message):
    if advert_message is not None:
        msg = await message.answer("<code>Announcement started</code>")
        users = await get_user_ids()
        num = 0
        blocked = 0
        errors = 0
        for user_id in users:
            try:
                await advert_message.send_copy(user_id)
                num += 1
            except TelegramForbiddenError:
                blocked += 1
                logging.debug(f"User {user_id} blocked the bot")
            except TelegramBadRequest as e:
                errors += 1
                logging.debug(f"Failed to send to {user_id}: {e}")
            except Exception as e:
                errors += 1
                logging.warning(f"Unexpected error sending to {user_id}: {e}")
            await sleep(0.04)
        await msg.delete()
        await message.answer(
            f"✅Message received by <b>{num}</b> users\n"
            f"🚫Blocked: <b>{blocked}</b>\n"
            f"❌Errors: <b>{errors}</b>"
        )
    else:
        await message.answer("⚠️You have not created a message yet")


@advert_router.message(F.text == "✏Edit message", IsAdmin())
async def adv_change(message: Message, state: FSMContext):
    await message.answer("📝Write new message", reply_markup=back_keyboard)
    await state.set_state(AdminMenu.add)


@advert_router.message(AdminMenu.add)
async def notify_text(message: Message, state: FSMContext):
    global advert_message
    advert_message = copy(message)
    await message.answer("✅Message added", reply_markup=admin_keyboard)
    await state.clear()
