from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext, filters
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from configparser import ConfigParser as configparser
import re
from requests import get as rget
import sqlite3
from time import time, sleep
from simplejson import loads as jloads
import logging

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
    sqlite_select_query = "SELECT * from Users"
    cursor.execute(sqlite_select_query)
    data = cursor.fetchall()
    res = list()
    for x in data:
        res.append(x[0])
    return res

#Команда /start
@dp.message_handler(commands=['start'])
async def send_start(message: types.Message):
    users = load_list()
    if message.chat.id not in users:
        cursor.execute(f'INSERT INTO Users VALUES ({message.chat.id}, {tCurrent()}, NULL)')
        sqlite.commit()
        text = f'<b>{message.chat.first_name} {message.chat.last_name}</b>\n@{message.chat.username}\n<code>{message.chat.id}</code>'
        await bot.send_message(logs, text, parse_mode='html')
        logging.info(f'{message.chat.first_name} {message.chat.last_name} @{message.chat.username} {message.chat.id}')
    await message.answer('Вы запуситили бота <b>No Watermark TikTok</b>\nЭтот бот позволяет скачивать видео из тиктока <i><b>без водяного знака</b></i>.\n<b>Отправьте ссылку на видео чтобы начать</b>', parse_mode="html")

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

@dp.message_handler(commands=["users", "len"])
async def send_notify(message: types.Message):
    if message.chat.id == admin_id or message.chat.id in second_id:
        cursor.execute("select * from Users")
        lenusr = len(cursor.fetchall())
        await message.answer(f'Пользователей в боте: <b>{lenusr}</b>', parse_mode='HTML')

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
    await message.answer(text, parse_mode='html', disable_web_page_preview=True)

@dp.message_handler(filters.Text(equals=["Проверить сообщение"], ignore_case=True), state=adv.menu)
async def adb_check(message: types.Message, state: FSMContext):
    global adv_text 
    if adv_text != None:
        mtype = adv_text[0]
        text = adv_text[1]
        markup = adv_text[2]
        file_id = adv_text[3]
        if mtype == 'text':
            await message.answer(text, reply_markup=markup,  parse_mode='html', disable_web_page_preview=True)
        elif mtype == 'photo':
            await message.answer_photo(file_id, caption=text, reply_markup=markup,  parse_mode='html')
        elif mtype == 'video':
            await message.answer_video(file_id, caption=text, reply_markup=markup,  parse_mode='html')
        elif mtype == 'animation':
            await message.answer_animation(file_id, caption=text, reply_markup=markup,  parse_mode='html')
        elif mtype == 'doc':
            await message.answer_document(file_id, caption=text, reply_markup=markup,  parse_mode='html')
    else:
        await message.answer('Вы не добавили сообщение')

@dp.message_handler(filters.Text(equals=["Отправить сообщение"], ignore_case=True), state=adv.menu)
async def adv_go(message: types.Message, state: FSMContext):
    global adv_text
    if adv_text != None:
        msg = await message.answer('<code>Началась рассылка</code>', parse_mode='html')
        num = 0
        users = load_list()
        mtype = adv_text[0]
        text = adv_text[1]
        markup = adv_text[2]
        file_id = adv_text[3]
        for x in users:
            try:
                if mtype == 'text':
                    await bot.send_message(x, text, reply_markup=markup,  parse_mode='html', disable_web_page_preview=True)
                elif mtype == 'photo':
                    await bot.send_photo(x, file_id, caption=text, reply_markup=markup,  parse_mode='html')
                elif mtype == 'video':
                    await bot.send_video(x, file_id, caption=text, reply_markup=markup,  parse_mode='html')
                elif mtype == 'animation':
                    await bot.send_animation(x, file_id, caption=text, reply_markup=markup,  parse_mode='html')
                elif mtype == 'doc':
                    await bot.send_document(x, file_id, caption=text, reply_markup=markup,  parse_mode='html')
                num += 1
            except:
                pass
            sleep(0.1)
        await msg.edit_text(f'Сообщение пришло <b>{num}</b> пользователям', parse_mode='html')
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
    if message.chat.id not in active:
        active.append(message.chat.id)
        url = "https://video-nwm.p.rapidapi.com/url/"
        querystring = {"url":f"{message.text}"}

        headers = {
            'x-rapidapi-host': "video-nwm.p.rapidapi.com",
            'x-rapidapi-key': api_key
            }

        msg = await message.answer('<code>Запрос видео...</code>', parse_mode='html')
        try:
            text = rget(url, headers=headers, params=querystring).json()
            if 'status' == '2':
                active.remove(message.chat.id)
                return await msg.edit_text('Недействительная ссылка!')
            active.remove(message.chat.id)
            playAddr = text['item']['video']['playAddr']
            await message.answer_chat_action('upload_video')
            await message.reply_video(playAddr[0], caption=podp_text, parse_mode='html')
            await msg.delete()
            a = cursor.execute(f'SELECT videos FROM Users WHERE id = {message.chat.id};')
            res = a.fetchall()[0][0]
            text = message.text
            if res is not None:
                text = res+f'\n{message.text}'
            cursor.execute(f'UPDATE Users SET videos = \'{text}\' WHERE id = {message.chat.id};')
            sqlite.commit()
            logging.info(f'{message.chat.id}: {message.text}')
        except:
            return await msg.edit_text('<b>Произошла ошибка!</b>\nПопробуйте еще раз, если ошибка не пропадет то сообщите в <a href=\'t.me/ttgrab_support_bot\'>Поддержку</a>', parse_mode='html')

if __name__ == "__main__":

    #Подключение sqlite
    sqlite = sqlite_init()
    #sqlite.row_factory = lambda cursor, row: row[0]
    cursor = sqlite.cursor()
    active = list()
    adv_text = None
    with open('podp.txt', 'r', encoding='utf-8') as f:
        podp_text = f.read()

    executor.start_polling(dp, skip_updates=True)
    sqlite.close()
    logging.info("Соединение с SQLite закрыто")