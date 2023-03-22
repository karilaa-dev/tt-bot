from asyncio import sleep

from aiogram import types
from aiogram.dispatcher import filters, FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, ContentType

from data.config import admin_ids
from data.loader import dp, cursor

advert_message = None


class AdminMenu(StatesGroup):
    menu = State()
    add = State()


admin_keyboard = ReplyKeyboardMarkup(True, resize_keyboard=True)
admin_keyboard.row('👁‍🗨Check message')
admin_keyboard.row('✏Edit message')
admin_keyboard.row('📢Send message')
admin_keyboard.row('🔽Hide keyboard')

back_keyboard = ReplyKeyboardMarkup(True, resize_keyboard=True)
back_keyboard.row('↩Return')


@dp.message_handler(filters.Text(equals=["↩return", "back"], ignore_case=True), state='*')
@dp.message_handler(commands=["stop", "cancel", "back"], state='*')
async def cancel(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids:
        await message.answer('↩You have returned', reply_markup=admin_keyboard)
        await state.finish()


@dp.message_handler(
    filters.Text(equals=["🔽Hide keyboard"]))
async def send_clear_keyboard(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('🔽You successfully hide the keyboard', reply_markup=ReplyKeyboardRemove())


@dp.message_handler(commands=['admin'])
async def send_admin(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('🤖You opened admin menu', reply_markup=admin_keyboard)


@dp.message_handler(filters.Text(equals=["👁‍🗨Check message"]))
async def adb_check(message: types.Message):
    if advert_message is not None:
        await advert_message.send_copy(message["from"]["id"], disable_web_page_preview=True)
    else:
        await message.answer('⚠️You have not created a message yet')


@dp.message_handler(
    filters.Text(equals=["📢Send message"]))
async def adv_go(message: types.Message):
    if advert_message is not None:
        msg = await message.answer('<code>Announcement started</code>')
        users = cursor.execute("SELECT id from users WHERE id > 0").fetchall()
        num = 0
        for x in users:
            try:
                await advert_message.send_copy(x[0], disable_web_page_preview=True)
                num += 1
            except:
                pass
            await sleep(0.04)
        await msg.delete()
        await message.answer(f'✅Message received by <b>{num}</b> users')
    else:
        await message.answer('⚠️You have not created a message yet')


@dp.message_handler(
    filters.Text(equals=["✏Edit message"]))
async def adv_change(message: types.Message):
    await message.answer('📝Write new message', reply_markup=back_keyboard)
    await AdminMenu.add.set()


@dp.message_handler(content_types=ContentType.ANY, state=AdminMenu.add)
async def notify_text(message: types.Message, state: FSMContext):
    global advert_message
    advert_message = message
    await message.answer('✅Message added', reply_markup=admin_keyboard)
    await state.finish()
