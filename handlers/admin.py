from asyncio import sleep

from aiogram import types
from truechecker import TrueChecker

from data.config import admin_ids, second_ids, bot_token
from data.loader import bot, cursor, dp
from misc.utils import tCurrent


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
        res = f'Пользователи\n - живы: {profile.users.active}\n - остановлены: {profile.users.stopped}\n - удалены: {profile.users.deleted}\n - отсутствуют: {profile.users.not_found}'
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
                                      caption='Список пользоватлей бота')


@dp.message_handler(commands=["stats"])
async def send_stats(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_ids:
        text = message.text.split(' ')
        if len(text) > 1:
            try:
                tnow = tCurrent()
                total = cursor.execute('SELECT COUNT(id) FROM users WHERE link = ?',
                                       [text[1].lower()]).fetchone()[0]
                total24h = cursor.execute(
                    'SELECT COUNT(id) FROM users WHERE link = ? AND time >= ?',
                    (text[1].lower(), tnow - 86400)).fetchone()[0]
                await message.answer(
                    f'По этой ссылке пришло <b>{total}</b> пользователей\nЗа 24 часа: <b>{total24h}</b>')
            except:
                await message.answer('Произошла ошибка')
        else:
            text = await bot_stats()
            await message.answer(text)
