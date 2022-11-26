from asyncio import sleep

from aiogram import types
from aiogram.dispatcher import filters, FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from data.config import admin_ids
from data.loader import dp, cursor, bot

adv_text = None


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


@dp.message_handler(filters.Text(equals=["↩назад", "назад"], ignore_case=True), state='*')
@dp.message_handler(commands=["stop", "cancel", "back"], state='*')
async def cancel(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids:
        await message.answer('↩You have returned', reply_markup=admin_keyboard)
        await state.finish()


@dp.message_handler(
    filters.Text(equals=["🔽Hide keyboard"]))
async def send_clear_keyb(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('🔽You successfully hide the keyboard', reply_markup=ReplyKeyboardRemove())


@dp.message_handler(commands=['admin'])
async def send_admin(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('🤖You opened admin menu', reply_markup=admin_keyboard)


@dp.message_handler(filters.Text(equals=["👁‍🗨Check message"]))
async def adb_check(message: types.Message):
    if adv_text is not None:
        if adv_text[0] == 'text':
            await message.answer(adv_text[1], reply_markup=adv_text[2],
                                 disable_web_page_preview=True,
                                 entities=adv_text[4])
        elif adv_text[0] == 'photo':
            await message.answer_photo(adv_text[3],
                                       caption=adv_text[1],
                                       reply_markup=adv_text[2],
                                       caption_entities=adv_text[4])
        elif adv_text[0] == 'gif':
            await message.answer_animation(adv_text[3],
                                           caption=adv_text[1],
                                           reply_markup=adv_text[2],
                                           caption_entities=adv_text[4])
        elif adv_text[0] == 'video':
            await message.answer_video(adv_text[3],
                                       caption=adv_text[1],
                                       reply_markup=adv_text[2],
                                       caption_entities=adv_text[4])
    else:
        await message.answer('⚠️You have not created a message yet')


@dp.message_handler(
    filters.Text(equals=["📢Send message"]))
async def adv_go(message: types.Message):
    if adv_text is not None:
        msg = await message.answer('<code>Announcement started</code>')
        users = cursor.execute("SELECT id from users").fetchall()
        num = 0
        for x in users:
            try:
                if adv_text[0] == 'text':
                    await bot.send_message(x[0], adv_text[1],
                                           reply_markup=adv_text[2],
                                           disable_web_page_preview=True,
                                           entities=adv_text[4])
                elif adv_text[0] == 'photo':
                    await bot.send_photo(x[0], adv_text[3],
                                         caption=adv_text[1],
                                         reply_markup=adv_text[2],
                                         caption_entities=adv_text[4])
                elif adv_text[0] == 'gif':
                    await bot.send_animation(x[0], adv_text[3],
                                             caption=adv_text[1],
                                             reply_markup=adv_text[2],
                                             caption_entities=adv_text[4])
                elif adv_text[0] == 'video':
                    await bot.send_video(x[0], adv_text[3],
                                         caption=adv_text[1],
                                         reply_markup=adv_text[2],
                                         caption_entities=adv_text[4])
                num += 1
            except:
                pass
            await sleep(0.05)
        await msg.delete()
        await message.answer(f'✅Message received by <b>{num}</b> users')
    else:
        await message.answer('⚠️You have not created a message yet')


@dp.message_handler(
    filters.Text(equals=["✏Edit message"]))
async def adv_change(message: types.Message):
    await message.answer('📝Write new message', reply_markup=back_keyboard)
    await AdminMenu.add.set()


@dp.message_handler(content_types=['text', 'photo', 'animation', 'video'], state=AdminMenu.add)
async def notify_text(message: types.Message, state: FSMContext):
    global adv_text
    if 'photo' in message:
        adv_text = ['photo', message['caption'], message.reply_markup,
                    message.photo[-1].file_id,
                    message.caption_entities]
    elif 'animation' in message:
        adv_text = ['gif', message['caption'], message.reply_markup,
                    message.animation.file_id,
                    message.caption_entities]
    elif 'video' in message:
        adv_text = ['video', message['caption'], message.reply_markup,
                    message.video.file_id,
                    message.caption_entities]
    else:
        adv_text = ['text', message['text'], message.reply_markup, None,
                    message.entities]
    await message.answer('✅Message added', reply_markup=admin_keyboard)
    await state.finish()
