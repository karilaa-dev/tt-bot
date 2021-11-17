from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext, filters
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from configparser import ConfigParser as configparser
import re
from requests import get as rget
import sqlite3
from time import time, sleep

#Загрузка конфига
config = configparser()
config.read("config.ini")
admin_id = int(config["bot"]["admin_id"])
bot_token = config["bot"]["token"]

#Инициализация либы aiogram
bot = Bot(token=bot_token)
dp = Dispatcher(bot, storage=MemoryStorage())

class states(StatesGroup):
    notify = State()
    notify1 = State()

def sqlite_init():
    try:
        sqlite = sqlite3.connect('sqlite.db', timeout=20)
        print("Подключен к SQLite")
        return sqlite
    except sqlite3.Error as error:
        print("Ошибка при подключении к sqlite", error)
        return exit()

def tCurrent():
    return int(time())

def load_list(cursor):
    sqlite_select_query = "SELECT * from Users"
    cursor.execute(sqlite_select_query)
    data = cursor.fetchall()
    res = list()
    for x in data:
        res.append(x[0])
    return res

async def ttdownoad(message):
    url = message.text
    dl_url = 'https://toolav.herokuapp.com/id/?video_id='

    mobile_pattern = re.compile(r'(https?://[^\s]+tiktok.com/[^\s@]+)') # re pattern for tiktok links from mobile, e.x. "vm.tiktok.com/"
    web_pattern = re.compile(r'(https?://www.tiktok.com/@[^\s]+/video/[0-9]+)') # re pattern for tiktok links from a web browser, e.x. "www.tiktok.com/@user"

    if mobile_pattern.search(url):
        r = rget(url).url # GET request to get the ID of the tiktok
        if r != 'https://www.tiktok.com/':
            tiktok_id = r.split('.html', 1)[0].split('/')[-1]
        else:
            return await message.answer('Недействительная ссылка!', parse_mode='HTML')

    elif web_pattern.search(url):
        tiktok_id = url.split('?', 1)[0].split('/')[-1]

    else:
        return await message.answer('Некоректная ссылка!')

    msg = await message.answer('<code>Выполняеться запрос видео</code>', parse_mode='HTML')
    r = rget(dl_url + tiktok_id)
    text = r.json()
    if 'status_code' in text:
        await msg.edit_text('Недействительная ссылка!', parse_mode='HTML')
    else:
        await msg.edit_text('<code>Отправка видео</code>', parse_mode='HTML')
        playAddr = text['item']['video']['playAddr']
        await message.answer_video(playAddr[0])
        await msg.delete()

#Команда /start
@dp.message_handler(commands=['start'])
async def send_start(message: types.Message):
    if message.chat.id not in users:
        cursor.execute(f'INSERT INTO Users VALUES ({message.chat.id}, {tCurrent()})')
        sqlite.commit()
        users.append(message.chat.id)
    await message.answer('Вы запуситили <b>ttdownload</b>', parse_mode="HTML")

@dp.message_handler(commands=["notify"])
async def send_notify(message: types.Message):
    if message.chat.id == admin_id:
        await message.answer('Введите сообщение')
        await states.notify.set()

@dp.message_handler(content_types=['video'], state=states.notify)
async def notify_load(message: types.Message, state: FSMContext):
    msg = await message.answer('<code>Началась рассылка</code>', parse_mode='HTML')
    num = 0
    for x in users:
        try:
            await bot.send_video(x, message.video.file_id, caption=message['caption'])
            num += 1
        except:
            pass
        sleep(0.1)
    await msg.edit_text(f'Сообщение пришло {num} пользователям')
    await state.finish()

@dp.message_handler(content_types=['photo'], state=states.notify)
async def notify_load(message: types.Message, state: FSMContext):
    msg = await message.answer('<code>Началась рассылка</code>', parse_mode='HTML')
    num = 0
    for x in users:
        try:
            await bot.send_photo(x, message.photo[-1].file_id, caption=message['caption'])
            num += 1
        except:
            pass
        sleep(0.1)
    await msg.edit_text(f'Сообщение пришло {num} пользователям')
    await state.finish()

@dp.message_handler(content_types=['animation'], state=states.notify)
async def notify_load(message: types.Message, state: FSMContext):
    msg = await message.answer('<code>Началась рассылка</code>', parse_mode='HTML')
    num = 0
    for x in users:
        try:
            await bot.send_animation(x, message.animation.file_id, caption=message['caption'])
            num += 1
        except:
            pass
        sleep(0.1)
    await msg.edit_text(f'Сообщение пришло {num} пользователям')
    await state.finish()

@dp.message_handler(content_types=['text'], state=states.notify)
async def notify_load(message: types.Message, state: FSMContext):
    msg = await message.answer('<code>Началась рассылка</code>', parse_mode='HTML')
    num = 0
    for x in users:
        try:
            await bot.send_message(x, message.text)
            num += 1
        except:
            pass
        sleep(0.1)
    await msg.edit_text(f'Сообщение пришло {num} пользователям')
    await state.finish()

@dp.message_handler(content_types=['document'], state=states.notify)
async def notify_load(message: types.Message, state: FSMContext):
    msg = await message.answer('<code>Началась рассылка</code>', parse_mode='HTML')
    num = 0
    for x in users:
        try:
            await bot.send_document(x, message.document.file_id, caption=message['caption'])
            num += 1
        except:
            pass
        sleep(0.1)
    await msg.edit_text(f'Сообщение пришло {num} пользователям')
    await state.finish()

@dp.message_handler()
async def send_ttdown(message: types.Message):
    await ttdownoad(message)

if __name__ == "__main__":
    sqlite = sqlite_init()
    cursor = sqlite.cursor()
    users = load_list(cursor)
    executor.start_polling(dp, skip_updates=True)
    sqlite.close()
    print("Соединение с SQLite закрыто")