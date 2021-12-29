from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext, filters
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from configparser import ConfigParser as configparser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re
from requests import get as rget
import sqlite3
from time import time, sleep, ctime
from simplejson import loads as jloads
import logging
import aiohttp

class ttapi:
    def __init__(self):
        self.session = aiohttp.ClientSession()

    async def url(self, text):
        url = f'https://api.reiyuura.me/api/dl/tiktokv2?url={text}'
        try:
            async with self.session.get(url) as req:
                try: res = await req.json()
                except: return 'connerror'
                return res['result']['Video_URL']['WithoutWM']
        except:
            return 'error'

    async def url_paid(self, text):
        url = "https://video-nwm.p.rapidapi.com/url/"
        querystring = {"url":f"{text}"}
        headers = {
            'x-rapidapi-host': "video-nwm.p.rapidapi.com",  
            'x-rapidapi-key': api_key}
        try:
            async with self.session.get(url, headers=headers, params=querystring) as req:
                try: res = await req.json()
                except: return 'connerror'
                if res['status'] == '1': return 'errorlink'
                return res['item']['video']['playAddr'][0]
        except:
            return 'error'

    async def url_paid2(self, text):
        url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        querystring = {"url":f"{text}","hd":"0"}
        headers = {
            'x-rapidapi-host': "tiktok-video-no-watermark2.p.rapidapi.com",
            'x-rapidapi-key': api_key}
        try:
            async with self.session.post(url, headers=headers, params=querystring) as req:
                try: res = await req.json()
                except: return 'connerror'
                if res['code'] == -1: return 'errorlink'
                return res['data']['play']
        except:
            return 'error'
        
    async def url_music(self, text):
        url = "https://tiktok-video-no-watermark2.p.rapidapi.com/music/info"
        querystring = {"url":f"{text}"}
        headers = {
            'x-rapidapi-host': "tiktok-video-no-watermark2.p.rapidapi.com",
            'x-rapidapi-key': api_key}
        try:
            async with self.session.post(url, headers=headers, params=querystring) as req:
                try: res = await req.json()
                except: return 'connerror'
                if res['code'] == -1: return 'errorlink'
                return res['data']['play'], res['data']['title'], res['data']['author']
        except:
            return 'error'

api = ttapi()

logging.basicConfig(encoding='utf-8', level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s", handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])

keyboard = ReplyKeyboardMarkup(True)
keyboard.row('Сообщение подписи')
keyboard.row('Глобальное сообщение')

keyboardmenu = ReplyKeyboardMarkup(True)
keyboardmenu.row('Проверить сообщение')
keyboardmenu.row('Изменить сообщение')
keyboardmenu.row('Отправить сообщение')
keyboardmenu.row('Назад')

keyboardmenupodp = ReplyKeyboardMarkup(True)
keyboardmenupodp.row('Проверить сообщение')
keyboardmenupodp.row('Изменить сообщение')
keyboardmenupodp.row('Назад')


keyboardback = ReplyKeyboardMarkup(True)
keyboardback.row('Назад')

#Загрузка конфига
config = configparser()
config.read("config.ini")
admin_id = int(config["bot"]["admin_id"])
second_id =  jloads(config["bot"]["second_id"])
bot_token = config["bot"]["token"]
api_key = config["bot"]["api_key"]
logs = config["bot"]["logs"]
upd_chat = config["bot"]["upd_chat"]
upd_id = config["bot"]["upd_id"]

#Инициализация либы aiogram
bot = Bot(token=bot_token)
dp = Dispatcher(bot, storage=MemoryStorage())

class adv(StatesGroup):
    menu = State()
    add = State()

class podp(StatesGroup):
    menu = State()
    add = State()

def sqlite_init():
    try:
        sqlite = sqlite3.connect('sqlite.db', timeout=20)
        logging.info('SQLite connected')
        return sqlite
    except sqlite3.Error as error:
        logging.error('Error while connecting to SQLite', error)
        return exit()

def tCurrent():
    return int(time())

def load_list():
    sqlite_select_query = "SELECT * from users"
    cursor.execute(sqlite_select_query)
    data = cursor.fetchall()
    res = list()
    for x in data:
        res.append(x[0])
    return res

async def bot_stats():
    tnow = tCurrent()
    users = cursor.execute("SELECT COUNT(id) FROM users").fetchall()[0][0]
    videos = cursor.execute("SELECT COUNT(id) FROM videos").fetchall()[0][0]
    music = cursor.execute("SELECT COUNT(id) FROM music").fetchall()[0][0]
    downl = videos + music
    users24 = cursor.execute(f"SELECT COUNT(id) FROM users WHERE time >= {tnow-86400}").fetchall()[0][0]
    videos24 = cursor.execute(f"SELECT COUNT(id) FROM videos WHERE time >= {tnow-86400}").fetchall()[0][0]
    music24 = cursor.execute(f"SELECT COUNT(id) FROM music WHERE time >= {tnow-86400}").fetchall()[0][0]
    downl24 = videos24 + music24
    return f'Пользователей: <b>{users}</b>\nМузыки: <b>{music}</b>\nСкачано: <b>{downl}</b>\n\n<b>За 24 часа</b>:\nНовых пользователей: <b>{users24}</b>\nМузыки: <b>{music24}</b>\nСкачано: <b>{downl24}</b>'

async def stats_log():
    text = await bot_stats()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=upd_chat, message_id=upd_id, text=text)

#Команда /start
@dp.message_handler(commands=['start'])
async def send_start(message: types.Message):
    users = load_list()
    if message.chat.id not in users:
        cursor.execute(f'INSERT INTO users VALUES ({message.chat.id}, {tCurrent()})')
        sqlite.commit()
        text = f'<b>{message.chat.first_name} {message.chat.last_name}</b>\n@{message.chat.username}\n<code>{message.chat.id}</code>'
        await bot.send_message(logs, text)
        logging.info(f'{message.chat.first_name} {message.chat.last_name} @{message.chat.username} {message.chat.id}')
    await message.answer('Вы запуситили бота <b>No Watermark TikTok</b>\nЭтот бот позволяет скачивать <b>видео/аудио</b> из тиктока <i><b>без водяного знака</b></i>.\nОтправьте ссылку на видео/аудио чтобы начать', parse_mode="html")

@dp.message_handler(filters.Text(equals=["назад"], ignore_case=True), state='*')
@dp.message_handler(commands=["stop", "cancel", "back"], state='*')
async def cancel(message: types.Message, state: FSMContext):
    if message.chat.id == admin_id:
        await message.answer('Вы вернулись назад', reply_markup=keyboard)
        await state.finish()

@dp.message_handler(commands=['admin'])
async def send_admin(message: types.Message):
    if message.chat.id == admin_id:
        await message.answer('Вы открыли админ меню', reply_markup=keyboard)

@dp.message_handler(commands=['reset'], state='*')
async def send_reset_ad(message: types.Message):
    if message.chat.id == admin_id:
        with open('podp.txt', 'w', encoding='utf-8') as f:
            with open('original.txt', 'r', encoding='utf-8') as r:
                text = r.read()
                f.write(text)
        global podp_text
        podp_text = text
        await message.answer('Вы успешно сбросили сообщение')

@dp.message_handler(commands=["export"], state='*')
async def send_stats(message: types.Message):
    if message.chat.id == admin_id:
        users = cursor.execute('SELECT id FROM users').fetchall()
        with open('users.txt', 'w') as f:
            for x in users:
                f.write(str(x[0])+'\n')
        await message.answer_document(open('users.txt', 'rb'), caption='Список пользоватлей бота')

@dp.message_handler(commands=["stats"])
async def send_stats(message: types.Message):
    if message.chat.id == admin_id or message.chat.id in second_id:
        text = await bot_stats()
        await message.answer(text)

@dp.message_handler(filters.Text(equals=["Сообщение подписи"], ignore_case=True))
async def podp_menu(message: types.Message, state: FSMContext):
    if message.chat.id == admin_id:
        await message.answer('Сообщение подписи', reply_markup=keyboardmenupodp)
        await podp.menu.set()

@dp.message_handler(filters.Text(equals=["Глобальное сообщение"], ignore_case=True))
async def adv_menu(message: types.Message, state: FSMContext):
    if message.chat.id == admin_id:
        await message.answer('Глобальное сообщение', reply_markup=keyboardmenu)
        await adv.menu.set()

@dp.message_handler(filters.Text(equals=["Проверить сообщение"], ignore_case=True), state=podp.menu)
async def podp_check(message: types.Message, state: FSMContext):
    with open('podp.txt', 'r', encoding='utf-8') as f:
        text = f.read()
    await message.answer(text, disable_web_page_preview=True)

@dp.message_handler(filters.Text(equals=["Проверить сообщение"], ignore_case=True), state=adv.menu)
async def adb_check(message: types.Message, state: FSMContext):
    global adv_text 
    if adv_text != None:
        mtype = adv_text[0]
        text = adv_text[1]
        markup = adv_text[2]
        file_id = adv_text[3]
        if mtype == 'text':
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        elif mtype == 'photo':
            await message.answer_photo(file_id, caption=text, reply_markup=markup)
        elif mtype == 'video':
            await message.answer_video(file_id, caption=text, reply_markup=markup)
        elif mtype == 'animation':
            await message.answer_animation(file_id, caption=text, reply_markup=markup)
        elif mtype == 'doc':
            await message.answer_document(file_id, caption=text, reply_markup=markup)
    else:
        await message.answer('Вы не добавили сообщение')

@dp.message_handler(filters.Text(equals=["Отправить сообщение"], ignore_case=True), state=adv.menu)
async def adv_go(message: types.Message, state: FSMContext):
    global adv_text
    if adv_text != None:
        msg = await message.answer('<code>Началась рассылка</code>')
        num = 0
        users = load_list()
        mtype = adv_text[0]
        text = adv_text[1]
        markup = adv_text[2]
        file_id = adv_text[3]
        for x in users:
            try:
                if mtype == 'text':
                    await bot.send_message(x, text, reply_markup=markup, disable_web_page_preview=True)
                elif mtype == 'photo':
                    await bot.send_photo(x, file_id, caption=text, reply_markup=markup)
                elif mtype == 'video':
                    await bot.send_video(x, file_id, caption=text, reply_markup=markup)
                elif mtype == 'animation':
                    await bot.send_animation(x, file_id, caption=text, reply_markup=markup)
                elif mtype == 'doc':
                    await bot.send_document(x, file_id, caption=text, reply_markup=markup)
                num += 1
            except:
                pass
            sleep(0.1)
        await msg.edit_text(f'Сообщение пришло <b>{num}</b> пользователям')
    else:
        await message.answer('Вы не добавили сообщение')

@dp.message_handler(filters.Text(equals=["Изменить сообщение"], ignore_case=True), state=podp.menu)
async def podp_change(message: types.Message, state: FSMContext):
    await message.answer('Введите новое сообщение используя html разметку', reply_markup=keyboardback)
    await podp.add.set()

@dp.message_handler(filters.Text(equals=["Изменить сообщение"], ignore_case=True), state=adv.menu)
async def podp_change(message: types.Message, state: FSMContext):
    await message.answer('Введите новое сообщение', reply_markup=keyboardback)
    await adv.add.set()

@dp.message_handler(state=podp.add)
async def podp_change_set(message: types.Message, state: FSMContext):
    with open('podp.txt', 'w', encoding='utf-8') as f:
        f.write(message.text)
    global podp_text
    podp_text = message.text
    await message.answer('Вы успешно изменили сообщение', reply_markup=keyboardmenupodp)
    await podp.menu.set()

@dp.message_handler(content_types=['text'], state=adv.add)
async def notify_text(message: types.Message, state: FSMContext):
    global adv_text
    adv_text = ['text', message['text'], message.reply_markup, None]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()

@dp.message_handler(content_types=['photo'], state=adv.add)
async def notify_photo(message: types.Message, state: FSMContext):
    global adv_text
    adv_text = ['photo', message['caption'], message.reply_markup, message.photo[-1].file_id]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()

@dp.message_handler(content_types=['video'], state=adv.add)
async def notify_video(message: types.Message, state: FSMContext):
    global adv_text
    adv_text = ['video', message['caption'], message.reply_markup, message.video.file_id]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()

@dp.message_handler(content_types=['animation'], state=adv.add)
async def notify_gif(message: types.Message, state: FSMContext):
    global adv_text
    adv_text = ['gif', message['caption'], message.reply_markup, message.animation.file_id]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()

@dp.message_handler(content_types=['document'], state=adv.add)
async def notify_doc(message: types.Message, state: FSMContext):
    global adv_text
    adv_text = ['doc', message['caption'], message.reply_markup, message.document.file_id]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()

@dp.message_handler()
async def send_ttdown(message: types.Message):
    msg = await message.answer('<code>Запрос видео...</code>')
    try:
        button = InlineKeyboardMarkup().add(InlineKeyboardButton('Ссылка на оригинал', url=message.text))
        playAddr = await api.url_paid2(message.text)
        if playAddr == 'errorlink':
            playAddr = await api.url_music(message.text)
            if playAddr == 'errorlink':
                return await msg.edit_text('Недействительная ссылка!')
            elif playAddr in ['error', 'connerror']: raise
            else:
                await message.answer_chat_action('upload_audio')
                res = f'<b>{playAddr[2]}</b> - {playAddr[1]}\n{podp_text}'
                await message.answer_audio(playAddr[0], caption=res, performer=playAddr[2], title=playAddr[1], reply_markup=button)
                await msg.delete()
                await message.delete()
                cursor.execute(f'INSERT INTO music VALUES (?,?,?,?)', (message.chat.id, tCurrent(), message.text, playAddr[0]))
                sqlite.commit()
                logging.info(f'{message.chat.id}: Music - {message.text}')
                return
        elif playAddr in ['error', 'connerror']: raise
        await message.answer_chat_action('upload_video')
        await message.answer_video(playAddr, caption=podp_text, reply_markup=button)
        await msg.delete()
        await message.delete()
        cursor.execute(f'INSERT INTO videos VALUES (?,?,?,?)', (message.chat.id, tCurrent(), message.text, playAddr))
        sqlite.commit()
        logging.info(f'{message.chat.id}: {message.text}')
    except:
        return await msg.edit_text('<b>Произошла ошибка!</b>\nПопробуйте еще раз, если ошибка не пропадет то сообщите в <a href=\'t.me/ttgrab_support_bot\'>Поддержку</a>')

if __name__ == "__main__":

    #Подключение sqlite
    sqlite = sqlite_init()
    #sqlite.row_factory = lambda cursor, row: row[0]
    cursor = sqlite.cursor()
    #active = list()
    adv_text = None
    with open('podp.txt', 'r', encoding='utf-8') as f:
        podp_text = f.read()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(stats_log)
    scheduler.add_job(stats_log, "interval", seconds=300)
    scheduler.start()

    executor.start_polling(dp, skip_updates=True)
    sqlite.close()
    logging.info("Соединение с SQLite закрыто")