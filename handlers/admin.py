from asyncio import sleep

from aiogram import types
from truechecker import TrueChecker

from data.config import admin_ids, second_ids, bot_token
from data.loader import bot, cursor, dp
from misc.utils import tCurrent, bot_stats, backup_dp

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def stats_keyboard(chat_type='all', stats_time=0):
    keyb = InlineKeyboardMarkup()
    times = ['24h', 'Week', 'Month', 'All']
    chat_types = ['Users', 'Groups', 'All']
    if stats_time == 0:
        times[3] = '✅'+times[3]
    elif stats_time == 2678400:
        times[2] = '✅'+times[2]
    elif stats_time == 604800:
        times[1] = '✅'+times[1]
    elif stats_time == 86400:
        times[0] = '✅'+times[0]

    if chat_type == 'all':
        chat_types[2] = '✅'+chat_types[2]
    elif chat_type == 'groups':
        chat_types[1] = '✅'+chat_types[1]
    elif chat_type == 'users':
        chat_types[0] = '✅'+chat_types[0]

    keyb.row(InlineKeyboardButton(times[0], callback_data=f'stats:{chat_type}/86400'),
             InlineKeyboardButton(times[1], callback_data=f'stats:{chat_type}/604800'),
             InlineKeyboardButton(times[2], callback_data=f'stats:{chat_type}/2678400'),
             InlineKeyboardButton(times[3], callback_data=f'stats:{chat_type}/0'))

    keyb.row(InlineKeyboardButton(chat_types[0], callback_data=f'stats:users/{stats_time}'),
             InlineKeyboardButton(chat_types[1], callback_data=f'stats:groups/{stats_time}'),
             InlineKeyboardButton(chat_types[2], callback_data=f'stats:all/{stats_time}'))

    keyb.add(InlineKeyboardButton('🔄Reload', callback_data=f'stats:{chat_type}/{stats_time}'))
    return keyb


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


@dp.message_handler(commands=['truecheck'])
async def truecheck(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_ids:
        users = cursor.execute('SELECT id FROM users').fetchall()
        with open('users.txt', 'w') as f:
            for x in users:
                f.write(str(x[0]) + '\n')
        checker = TrueChecker(bot_token)
        job = await checker.check_profile("users.txt")
        msg = await message.answer('Проверка запущена')
        progress = 0
        while int(progress) != 100:
            job = await checker.get_job_status(job.id)
            if job.progress != progress:
                await msg.edit_text(f'Проверено <b>{job.progress}%</b>')
            progress = job.progress
            await sleep(3)
        username = (await dp.bot.me)['username']
        profile = await checker.get_profile(username)
        res = f'Users\n - alive: {profile.users.active}\n - stopped: {profile.users.stopped}\n - deleted: {profile.users.deleted}\n - not found: {profile.users.not_found}'
        await msg.delete()
        await message.answer(res)
        await checker.close()


@dp.message_handler(commands=["export"], state='*')
async def export_users(message: types.Message):
    if message["from"]["id"] in admin_ids:
        users = cursor.execute('SELECT id FROM users').fetchall()
        with open('users.txt', 'w') as f:
            for x in users:
                f.write(str(x[0]) + '\n')
        await message.answer_document(open('users.txt', 'rb'),
                                      caption='User list')


@dp.message_handler(commands=["backup"], state='*')
async def backup(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_ids:
        await backup_dp(message.from_user.id)


@dp.message_handler(commands=["stats"], state='*')
async def send_stats(message: types.Message):
    if message["from"]["id"] in admin_ids+second_ids:
        text = message.text.split(' ')
        if len(text) > 1:
            try:
                time_now = tCurrent()
                total = cursor.execute('SELECT COUNT(id) FROM users WHERE link = ?',
                                       [text[1].lower()]).fetchone()[0]
                total24h = cursor.execute(
                    'SELECT COUNT(id) FROM users WHERE link = ? AND time >= ?',
                    (text[1].lower(), time_now - 86400)).fetchone()[0]
                await message.answer(
                    f'This link was followed by <b>{total}</b> users\nBy 24 hours: <b>{total24h}</b>')
            except:
                await message.answer('Error')
        else:
            temp = await message.answer('Loading...')
            keyb = stats_keyboard()
            await temp.edit_text(bot_stats(), reply_markup=keyb)


@dp.callback_query_handler(lambda c: c.data.startswith('stats:'))
async def stats_callback(call: types.CallbackQuery):
    group_type, stats_time = call.data.split(':')[1].split('/')
    stats_time = int(stats_time)
    await call.message.edit_text('Loading...')
    keyb = stats_keyboard(group_type, stats_time)
    await call.message.edit_text(bot_stats(group_type, stats_time), reply_markup=keyb)
    await call.answer()
