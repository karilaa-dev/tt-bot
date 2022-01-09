from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext, filters
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
from configparser import ConfigParser as configparser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re
import sqlite3
from time import time, sleep, ctime
from simplejson import loads as jloads
import logging
import aiosonic

class ttapi:
    def __init__(self, api_key):
        self.url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        self.headers = {
            'x-rapidapi-host': "tiktok-video-no-watermark2.p.rapidapi.com",
            'x-rapidapi-key': api_key
            }

    async def url_free(self, id):
        try:
            client = aiosonic.HTTPClient()
            url = f'https://api-va.tiktokv.com/aweme/v1/multi/aweme/detail/?aweme_ids=[{id}]'
            req = await client.post(url)
            try: res = jloads(await req.content())
            except: return 'connerror'
            if res['status_code'] != 0: return 'errorlink'
            return {
                    'url': res['aweme_details'][0]['video']['play_addr']['url_list'][0],
                    'id': id,
                }
        except:
            return 'error'

    async def url_paid(self, text):
        querystring = {"url":f"{text}","hd":"0"}
        try:
            client = aiosonic.HTTPClient()
            req = await client.post(self.url, headers=self.headers, data=querystring)
            try: res = jloads(await req.content())
            except: return 'connerror'
            if res['code'] == -1: return 'errorlink'
            return {
                    'url': res['data']['play'],
                    'id': res['data']['music_info']['id'],
                }
        except:
            return 'error'
        
    async def url_free_music(self, id):
        try:
            client = aiosonic.HTTPClient()
            url = f'https://api-va.tiktokv.com/aweme/v1/multi/aweme/detail/?aweme_ids=[{id}]'
            req = await client.post(url)
            try: res = jloads(await req.content())
            except: return 'connerror'
            if res['status_code'] != 0: return 'errorlink'
            return {
                'url': res['aweme_details'][0]['music']['play_url']['uri'],
                'title': res['aweme_details'][0]['music']['title'],
                'author': res['aweme_details'][0]['music']['author'],
                'duration': res['aweme_details'][0]['music']['duration'],
                'cover': res['aweme_details'][0]['music']['cover_large']['url_list'][0]
                }
        except:
            return 'error'

    async def url_paid_music(self, text):
        querystring = {"url":f"{text}"}
        try:
            client = aiosonic.HTTPClient()
            req = await client.post(self.url+'music/info', headers=self.headers, data=querystring)
            try: res = jloads(await req.content())
            except: return 'connerror'
            if res['code'] == -1: return 'errorlink'
            return {
                'url': res['data']['play'],
                'title': res['data']['title'],
                'author': res['data']['author'],
                'duration': res['data']['duration'],
                'cover': res['data']['cover']
                }
        except:
            return 'error'

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-5.5s]  %(message)s", handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)

keyboard = ReplyKeyboardMarkup(True)
keyboard.row('Сообщение подписи')
keyboard.row('Глобальное сообщение')
keyboard.row('Скрыть клавиатуру')

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

inlinelang = InlineKeyboardMarkup()
inlinelang.add(InlineKeyboardButton('English🇺🇸', callback_data='lang/en'))
inlinelang.add(InlineKeyboardButton('Русский🇷🇺', callback_data='lang/ru'))
inlinelang.add(InlineKeyboardButton('O\'zbekiston🇺🇿', callback_data='lang/uz'))

#Загрузка конфига
config = configparser()
config.read("config.ini")
admin_ids = jloads(config["bot"]["admin_id"])
second_id =  jloads(config["bot"]["second_id"])
bot_token = config["bot"]["token"]
api_key = config["bot"]["api_key"]
logs = config["bot"]["logs"]
upd_chat = config["bot"]["upd_chat"]
upd_id = config["bot"]["upd_id"]

#Инициализация либы aiogram
bot = Bot(token=bot_token, parse_mode='html')
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
    groups = cursor.execute("SELECT COUNT(id) FROM groups").fetchall()[0][0]
    users24 = cursor.execute(f"SELECT COUNT(id) FROM users WHERE time >= {tnow-86400}").fetchall()[0][0]
    videos24 = cursor.execute(f"SELECT COUNT(id) FROM videos WHERE time >= {tnow-86400}").fetchall()[0][0]
    music24 = cursor.execute(f"SELECT COUNT(id) FROM music WHERE time >= {tnow-86400}").fetchall()[0][0]
    groups24 = cursor.execute(f"SELECT COUNT(id) FROM groups WHERE time >= {tnow-86400}").fetchall()[0][0]
    videos24u = cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM videos where time >= {tnow-86400}").fetchall()[0][0]    
    return f'Пользователей: <b>{users}</b>\nМузыки: <b>{music}</b>\nВидео: <b>{videos}</b>\nВ групах: <b>{groups}</b>\n\n<b>За 24 часа</b>:\nНовых пользователей: <b>{users24}</b>\nМузыки: <b>{music24}</b>\nВидео: <b>{videos24}</b>\nУникальных: <b>{videos24u}</b>\nВ групах: <b>{groups24}</b>'

async def stats_log():
    text = await bot_stats()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=upd_chat, message_id=upd_id, text=text)

#Команда /start
@dp.message_handler(commands=['start'])
async def send_start(message: types.Message):
    users = load_list()
    first_start = False
    if message["from"]["id"] not in users:
        first_start = True
        lang = message['from']['language_code']
        cursor.execute(f'INSERT INTO users VALUES (?, ?, ?)', (message["from"]["id"], tCurrent(), message["from"]["language_code"]))
        sqlite.commit()
        text = f'<b>{message.chat.first_name} {message.chat.last_name}</b>\n@{message.chat.username}\n<code>{message["from"]["id"]}</code>'
        await bot.send_message(logs, text)
        logging.info(f'{message.chat.first_name} {message.chat.last_name} @{message.chat.username} {message["from"]["id"]}')
    else:
        lang_req = cursor.execute(f"SELECT lang FROM users WHERE id = {message['from']['id']}").fetchone()[0]
        if lang_req is None:
            lang = message['from']['language_code']
        else:
            lang = lang_req[0]
    if lang in ['ru', 'ua']:
        start_text = start_texts[0]
        lang_text = lang_texts[0]
    elif lang == 'uz':
        start_text = start_texts[2]
        lang_text = lang_texts[2]
    else:
        start_text = start_texts[1]
        lang_text = lang_texts[1]
    await message.answer(start_text)
    if first_start is True:
        await message.answer(lang_text)

@dp.message_handler(filters.Text(equals=["назад"], ignore_case=True), state='*')
@dp.message_handler(commands=["stop", "cancel", "back"], state='*')
async def cancel(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids:
        await message.answer('Вы вернулись назад', reply_markup=keyboard)
        await state.finish()

@dp.message_handler(filters.Text(equals=["Скрыть клавиатуру"], ignore_case=True))
async def send_clear_keyb(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('Вы успешно скрыли клавиатуру', reply_markup=ReplyKeyboardRemove())

@dp.message_handler(commands=['admin'])
async def send_admin(message: types.Message):
    if message["from"]["id"] in admin_ids:
        await message.answer('Вы открыли админ меню', reply_markup=keyboard)

@dp.message_handler(commands=['reset'], state='*')
async def send_reset_ad(message: types.Message):
    if message["from"]["id"] in admin_ids:
        with open('podp.txt', 'w', encoding='utf-8') as f:
            f.write('')
        global podp_text
        podp_text = ''
        await message.answer('Вы успешно сбросили сообщение')

@dp.message_handler(commands=['lang'], state='*')
async def send_reset_ad(message: types.Message):
    if message.chat.type == 'private':
        await message.answer('Select language:', reply_markup=inlinelang)

@dp.message_handler(commands=['change'], state='*')
async def send_reset_ad(message: types.Message):
    if message["from"]["id"] in admin_ids:
        global api_type
        if api_type == 'free':
            api_type = 'paid'
        else:
            api_type = 'free'
        with open('api.txt', 'w', encoding='utf-8') as f:
            f.write(api_type)
        await message.answer(f'Вы успешно изменили апи на <code>{api_type}</code>')

@dp.message_handler(commands=["export"], state='*')
async def send_stats(message: types.Message):
    if message["from"]["id"] in admin_ids:
        users = cursor.execute('SELECT id FROM users').fetchall()
        with open('users.txt', 'w') as f:
            for x in users:
                f.write(str(x[0])+'\n')
        await message.answer_document(open('users.txt', 'rb'), caption='Список пользоватлей бота')

@dp.message_handler(commands=["stats"])
async def send_stats(message: types.Message):
    if message["from"]["id"] in admin_ids or message["from"]["id"] in second_id:
        text = await bot_stats()
        await message.answer(text)

@dp.message_handler(filters.Text(equals=["Сообщение подписи"], ignore_case=True))
async def podp_menu(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids:
        await message.answer('Сообщение подписи', reply_markup=keyboardmenupodp)
        await podp.menu.set()

@dp.message_handler(filters.Text(equals=["Глобальное сообщение"], ignore_case=True))
async def adv_menu(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids:
        await message.answer('Глобальное сообщение', reply_markup=keyboardmenu)
        await adv.menu.set()

@dp.message_handler(filters.Text(equals=["Проверить сообщение"], ignore_case=True), state=podp.menu)
async def podp_check(message: types.Message, state: FSMContext):
    with open('podp.txt', 'r', encoding='utf-8') as f:
        text = f.read()
    if text != '':
        await message.answer(text, disable_web_page_preview=True)
    else:
        await message.answer('Вы не добавили сообщение подписи', disable_web_page_preview=True)

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
    await message.answer('Введите новое сообщение используя html разметку', reply_markup=keyboardback)
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

@dp.callback_query_handler(lambda call: call.data.startswith('id') or call.data.startswith('music'), state='*')
async def inline_music(callback_query: types.CallbackQuery):
    cht_type = callback_query.message.chat.type
    cht_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    cdata = callback_query.data
    lang_req = cursor.execute(f"SELECT lang FROM users WHERE id = {from_id}").fetchone()
    if lang_req is None:
        lang = callback_query['from']['language_code']
    else:
        lang = lang_req[0]
    msg = await bot.send_message(cht_id, '⏳')
    try:
        if cdata.startswith('id'):
            url = callback_query.data.lstrip('id/')
            playAddr = await api.url_free_music(url)
        elif cdata.startswith('music'):
            url = callback_query.data.lstrip('music/')
            playAddr = await api.url_paid_music(url)
        if playAddr in ['error', 'connerror', 'errorlink']: raise
        await bot.send_chat_action(cht_id, 'upload_document')
        if lang in ['ru', 'ua']:
            res = f'<b>{bot_tag}</b>\n\n<a href="{playAddr["cover"]}">Обложка</a>'
        elif lang == 'uz':
            res = f'<b>{bot_tag}</b>\n\n<a href="{playAddr["cover"]}">Rasmi</a>'
        else:
            res = f'<b>{bot_tag}</b>\n\n<a href="{playAddr["cover"]}">Song cover</a>'
        aud = InputFile.from_url(url=playAddr['url'])
        await bot.send_audio(cht_id, aud, caption=res, title=playAddr['title'], performer=playAddr['author'], duration=playAddr['duration'], thumb=playAddr['cover'])
        await msg.delete()
        try:
            cursor.execute(f'INSERT INTO music VALUES (?,?,?,?)', (callback_query["from"]["id"], tCurrent(), url, playAddr['url']))
            sqlite.commit()
            logging.info(f'{callback_query["from"]["id"]}: Music - {url}')
        except:
            logging.error(f'Неудалось записать в бд')
    except:
        try: await msg.delete()
        except: pass
        if cht_type == 'private':
            if lang in ['ru', 'ua']:
                error_msg = error_msgs[0]
            elif lang == 'uz':
                error_msg = error_msgs[2]
            else:
                error_msg = error_msgs[1]
            await bot.send_message(cht_id, error_msg)
    return await callback_query.answer()

@dp.callback_query_handler(lambda call: call.data.startswith('lang'), state='*')
async def inline_lang(callback_query: types.CallbackQuery):
    cht_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    cdata = callback_query.data
    lang = cdata.lstrip('lang/')
    lang_texts = ['Установлен язык Русский🇷🇺',
                'The language is set to English🇺🇸',
                'Õzbek🇺🇿 tilli o’rnatildi'
                ]
    try:
        cursor.execute(f'UPDATE users SET lang = "{lang}" WHERE id = {from_id}')
        sqlite.commit()
        if lang == 'ru':
            text = lang_texts[0]
        elif lang == 'uz':
            text = lang_texts[2]
        else:
            text = lang_texts[1]
        await bot.delete_message(cht_id, msg_id)
        await bot.send_message(from_id, text)
    except:
        pass
    return await callback_query.answer()

@dp.message_handler()
async def send_ttdown(message: types.Message):
    try:
        lang_req = cursor.execute(f"SELECT lang FROM users WHERE id = {message['from']['id']}").fetchone()
        if lang_req is None:
            lang = message['from']['language_code']
        else:
            lang = lang_req[0]
        if web_re.match(message.text) is not None:
            if message.chat.type == 'private':
                msg = await message.answer('⏳')
            else:
                msg = await message.reply('⏳')
            link = web_re.findall(message.text)[0]
            if api_type == 'free':
                id = red_re.findall(message.text)[0]
                playAddr = await api.url_free(id)
                url_type = 'free'
            else:
                playAddr = await api.url_paid(link)
                url_type = 'paid'
            urltype = 'video'
            if playAddr == 'errorlink': urltype = 'error'
            elif playAddr in ['error', 'connerror']: raise
        elif mob_re.match(message.text) is not None:
            if message.chat.type == 'private':
                msg = await message.answer('⏳')
            else:
                msg = await message.reply('⏳')
            link = mob_re.findall(message.text)[0]
            if api_type == 'free':
                client = aiosonic.HTTPClient()
                req = await client.get(message.text)
                res = await req.text()
                url_id = red_re.findall(res)[0]
                playAddr = await api.url_free(url_id)
                url_type = 'free'
            else:
                playAddr = await api.url_paid(link)
                url_type = 'paid'
            urltype = 'video'
            if playAddr == 'errorlink':
                playAddr = await api.url_music(link)
                urltype = 'music'
                if playAddr == 'errorlink': urltype = 'error'
                elif playAddr in ['error', 'connerror']: raise
            elif playAddr in ['error', 'connerror']: raise
        else:
            urltype = 'none'
        if urltype == 'video':
            await message.answer_chat_action('upload_video')
            if url_type == 'paid':
                button_id = f'music/{playAddr["id"]}'
            else:
                button_id = f'id/{playAddr["id"]}'
            if lang in ['ru', 'ua']:
                res = f'<b>{bot_tag}</b>\n\n<a href="{link}">Оригинал</a>'
                button_text = 'Скачать звук'
            elif lang == 'uz':
                res = f'<b>{bot_tag}</b>\n\n<a href="{link}">Original</a>'
                button_text = 'Товушни йозиб олиш'
            else:
                res = f'<b>{bot_tag}</b>\n\n<a href="{link}">Source</a>'
                button_text = 'Get Sound'
            music = InlineKeyboardMarkup().add(InlineKeyboardButton(button_text, callback_data=button_id))
            if message.chat.type == 'private':
                await message.answer_video(playAddr['url'], caption=res, reply_markup=music)
            else:
                await message.reply_video(playAddr['url'], caption=res, reply_markup=music)
            await msg.delete()
            try:
                if message.chat.type == 'private':
                    cursor.execute(f'INSERT INTO videos VALUES (?,?,?,?)', (message["from"]["id"], tCurrent(), link, playAddr['url']))
                else:
                    cursor.execute(f'INSERT INTO groups VALUES (?,?,?,?)', (message["chat"]["id"], tCurrent(), link, playAddr['url']))
                sqlite.commit()
                logging.info(f'{message["from"]["id"]}: {link}')
            except:
                logging.error(f'Неудалось записать в бд')
        elif urltype == 'error':
            if message.chat.type == 'private':
                if lang in ['ru', 'ua']:
                    error_link = 'Возможно что-то не так с вашей ссылкой🥲'
                elif lang == 'uz':
                    error_link = 'Sizning silkangiz bilan qandaydur hato hato bo’r🥲'
                else:
                    error_link = 'Probably something wrong with your link🥲'
                await msg.edit_text(error_link)
            else:
                await msg.delete()
            return
        elif urltype == 'none':
            if message.chat.type == 'private':
                if lang in ['ru', 'ua']:
                    error_link = 'Возможно что-то не так с вашей ссылкой🥲'
                elif lang == 'uz':
                    error_link = 'Sizning silkangiz bilan qandaydur hato hato bo’r🥲'
                else:
                    error_link = 'Probably something wrong with your link🥲'
                await message.answer(error_link)
            return
        else:
            return
        if message.chat.type == 'private' and podp_text != '':
           await message.answer(podp_text)
    except:
        try: await msg.delete()
        except: pass
        if message.chat.type == 'private':
            if lang in ['ru', 'ua']:
                error_msg = error_msgs[0]
            elif lang == 'uz':
                error_msg = error_msgs[2]
            else:
                error_msg = error_msgs[1]
            await message.answer(error_msg)
        return

if __name__ == "__main__":

    web_re = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
    mus_re = re.compile(r'https?://www.tiktok.com/music/[^\s]+')
    mob_re = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
    red_re = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')

    api = ttapi(api_key)

    error_msgs = ['<b>Что-то пошло не так🥲</b>\nНе могли бы вы попробовать еще раз?…',
                '<b>Something went wrong🥲</b>\nCould you please try again?…',
                '<b>Nimadur hato ketdi🥲</b>\nYana bir marta harakat qila olasizmi?…'
                ]

    lang_texts = ['Установлен язык Русский🇷🇺.\nЕго можно изменить командой /lang',
                'The language is set to English🇺🇸.\nIt can be changed with the /lang command',
                'Õzbek🇺🇿 tilli o’rnatildi.\nTilni almashtirish uchun /lang'
                ]

    start_texts = ['Привет, это бот для скачивания\nвидео и прочего из тиктока🎧\nФункции\n-Отправьте ссылку на видео, звук и получите результат через 2-3 секунды\n-Бот работает в группах💪(чтобы использовать его там добавьте его в группу и дайте ему права администратора) не волнуйтесь, бот никогда не будет спамить рекламой😉\n\nС наилучшими пожеланиями команда @unusone🦈',
                'Hi there, that’s bot for downloading\nvideos and other staff from tiktok🎧\nFeatures\n-Send link to video, sound and get result in 2-3 seconds\n-Bot works in groups💪(to use it there add it to group and give him admin rights)don’t worry bot will never spam advertisement😉\n\nWith best regards @unusone🦈team',
                'Ассаламу алейкум, bu bot TikTokdan🎧 harhil kontent yozib olish uchun.\nFunkcialari:\n-Botga videoni,tovushni silkasini tashlang va tayyor jovobni 1-2 sekundda oling.\n-Grupalarda ishlash💪(botga admin status berish kerak boladi)\nVa havotir olmang bot hech qayerga reklama tashamaydi.😉\n\nEng zo’r niyatlar bilan @unusone komandasi.🦈'
                ]

    #Подключение sqlite
    sqlite = sqlite_init()
    cursor = sqlite.cursor()
    adv_text = None
    with open('api.txt', 'r', encoding='utf-8') as f:
            api_type = f.read()
    with open('bot_tag.txt', 'r', encoding='utf-8') as f:
        bot_tag = f.read()
    with open('podp.txt', 'r', encoding='utf-8') as f:
        podp_text = f.read()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(stats_log)
    scheduler.add_job(stats_log, "interval", seconds=300)
    scheduler.start()

    executor.start_polling(dp, skip_updates=True)
    sqlite.close()
    logging.info("Соединение с SQLite закрыто")