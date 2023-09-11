from asyncio import sleep

from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from data.config import admin_ids
from data.loader import cursor

advert_router = Router(name=__name__)

advert_message: types.Message = None

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
async def cancel(message: types.Message, state: FSMContext):
    if message.from_user.id in admin_ids:
        await message.answer('↩You have returned', reply_markup=admin_keyboard)
        await state.clear()


@advert_router.message(F.text == "🔽Hide keyboard")
async def send_clear_keyboard(message: types.Message):
    if message.from_user.id in admin_ids:
        await message.answer('🔽You successfully hide the keyboard', reply_markup=ReplyKeyboardRemove())


@advert_router.message(Command("admin"))
async def send_admin(message: types.Message):
    if message.from_user.id in admin_ids:
        await message.answer('🤖You opened admin menu', reply_markup=admin_keyboard)


@advert_router.message(F.text == "👁‍🗨Check message")
async def adb_check(message: types.Message):
    if advert_message is not None:
        await advert_message.copy_to(message.from_user.id)
    else:
        await message.answer('⚠️You have not created a message yet')


@advert_router.message(F.text == "📢Send message")
async def adv_go(message: types.Message):
    if advert_message is not None:
        msg = await message.answer('<code>Announcement started</code>')
        users = cursor.execute("SELECT id from users WHERE id > 0").fetchall()
        num = 0
        for x in users:
            try:
                await advert_message.copy_to(x[0])
                num += 1
            except:
                pass
            await sleep(0.04)
        await msg.delete()
        await message.answer(f'✅Message received by <b>{num}</b> users')
    else:
        await message.answer('⚠️You have not created a message yet')


@advert_router.message(F.text == "✏Edit message")
async def adv_change(message: types.Message, state: FSMContext):
    await message.answer('📝Write new message', reply_markup=back_keyboard)
    await state.set_state(AdminMenu.add)


@advert_router.message(AdminMenu.add)
async def notify_text(message: types.Message, state: FSMContext):
    global advert_message
    advert_message = message
    await message.answer('✅Message added', reply_markup=admin_keyboard)
    await state.clear()
