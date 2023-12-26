from asyncio import sleep
from copy import copy

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from data.loader import cursor, bot
from misc.utils import IsAdmin

advert_router = Router(name=__name__)

advert_message: Message = None

admin_keyboard = ReplyKeyboardBuilder()
admin_keyboard.button(text='👁‍🗨Check message')
admin_keyboard.button(text='✏Edit message')
admin_keyboard.button(text='📢Send message')
admin_keyboard.button(text='🔽Hide keyboard')
admin_keyboard.adjust(2, 1, 1)
admin_keyboard = admin_keyboard.as_markup(resize_keyboard=True)

back_keyboard = ReplyKeyboardBuilder()
back_keyboard.button(text='↩Return')
back_keyboard = back_keyboard.as_markup(resize_keyboard=True)


class AdminMenu(StatesGroup):
    menu = State()
    add = State()


@advert_router.message(F.text == '↩Return')
@advert_router.message(Command("stop", "cancel", "back"))
async def cancel(message: Message, state: FSMContext):
    await message.answer('↩You have returned', reply_markup=admin_keyboard)
    await state.clear()


@advert_router.message(F.text == "🔽Hide keyboard")
@advert_router.message(Command("hide"))
async def send_clear_keyboard(message: Message):
    await message.answer('🔽You successfully hide the keyboard', reply_markup=ReplyKeyboardRemove())


@advert_router.message(Command("admin"), IsAdmin())
async def send_admin(message: Message):
    await message.answer('🤖You opened admin menu', reply_markup=admin_keyboard)


@advert_router.message(F.text == "👁‍🗨Check message", IsAdmin())
async def adb_check(message: Message):
    if advert_message is not None:
        await advert_message.send_copy(message.from_user.id)
    else:
        await message.answer('⚠️You have not created a message yet')


@advert_router.message(F.text == "📢Send message", IsAdmin())
async def adv_go(message: Message):
    if advert_message is not None:
        msg = await message.answer('<code>Announcement started</code>')
        users = cursor.execute("SELECT id from users WHERE id > 0").fetchall()
        num = 0
        for x in users:
            try:
                await advert_message.send_copy(x[0])
                num += 1
            except:
                pass
            await sleep(0.04)
        await msg.delete()
        await message.answer(f'✅Message received by <b>{num}</b> users')
    else:
        await message.answer('⚠️You have not created a message yet')


@advert_router.message(F.text == "✏Edit message", IsAdmin())
async def adv_change(message: Message, state: FSMContext):
    await message.answer('📝Write new message', reply_markup=back_keyboard)
    await state.set_state(AdminMenu.add)


@advert_router.message(AdminMenu.add)
async def notify_text(message: Message, state: FSMContext):
    global advert_message
    advert_message = copy(message)
    await message.answer('✅Message added', reply_markup=admin_keyboard)
    await state.clear()
