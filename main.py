from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import FSMContext, filters
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
from aiogram.bot.api import TelegramAPIServer
from configparser import ConfigParser as configparser
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import re
import sqlite3
from time import time, sleep, ctime
from simplejson import loads as jloads
import logging
import aiosonic
from locale import locale
from truechecker import TrueChecker

def lang_func(message):
    try:
        try:
            lang_req = cursor.execute(f"SELECT lang FROM users WHERE id = {message['from']['id']}").fetchone()[0]
        except:
            lang_req = None
        if lang_req is not None:
            lang = lang_req
        else:
            lang = message['from']['language_code']
            if lang not in locale['langs']: raise
            cursor.execute(f'UPDATE users SET lang = "{lang}" WHERE id = {message["from"]["id"]}')
            sqlite.commit()
        return lang
    except:
         return 'en'

class ttapi:
    def __init__(self, api_key):
        self.url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        self.free_url = "https://api-va.tiktokv.com/aweme/v1/multi/aweme/detail/?aweme_ids=[{}]"
        self.headers = {
            'x-rapidapi-host': "tiktok-video-no-watermark2.p.rapidapi.com",
            'x-rapidapi-key': api_key
            }

    async def url_free(self, id):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.free_url.format(id))
            try: res = jloads(await req.content())
            except: return 'connerror'
            if res['status_code'] != 0: return 'errorlink'
            return {
                    'url': res['aweme_details'][0]['video']['play_addr']['url_list'][0],
                    'id': id,
                    'cover': res['aweme_details'][0]['video']['origin_cover']['url_list'][0],
                    'width': res['aweme_details'][0]['video']['play_addr']['width'],
                    'height': res['aweme_details'][0]['video']['play_addr']['height'],
                    'duration': res['aweme_details'][0]['video']['duration']
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
                    'cover': res['data']['origin_cover'],
                    'width': 720,
                    'height': 1280,
                    'duration': 0
                }
        except:
            return 'error'
        
    async def url_free_music(self, id):
        try:
            async with aiosonic.HTTPClient() as client:
                req = await client.post(self.free_url.format(id))
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
for x in locale['langs']:
    inlinelang.add(InlineKeyboardButton(locale[x]['lang_name'], callback_data=f'lang/{x}'))

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
local_server = TelegramAPIServer.from_base(config["bot"]["tg_server"])

#Инициализация либы aiogram
bot = Bot(token=bot_token, server=local_server, parse_mode='html')
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
    return locale['stats'].format(users, music, videos, users24, music24, videos24, videos24u, groups, groups24)

async def stats_log():
    text = await bot_stats()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=upd_chat, message_id=upd_id, text=text)

#Команда /start
@dp.message_handler(commands=['start'], chat_type=types.ChatType.PRIVATE)
async def send_start(message: types.Message):
    req = cursor.execute('SELECT EXISTS(SELECT 1 FROM users WHERE id = ?)', [message.chat.id]).fetchone()[0]
    lang = lang_func(message)
    if req == 0:
        cursor.execute(f'INSERT INTO users VALUES (?, ?, ?)', (message["from"]["id"], tCurrent(), lang))
        sqlite.commit()
        text = f'<b>{message.chat.first_name} {message.chat.last_name}</b>\n@{message.chat.username}\n<code>{message["from"]["id"]}</code>'
        await bot.send_message(logs, text)
        logging.info(f'{message.chat.first_name} {message.chat.last_name} @{message.chat.username} {message["from"]["id"]}')
    await message.answer(locale[lang]['start'])
    await message.answer(locale[lang]['lang_start'])

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

@dp.message_handler(commands=['truecheck'])
async def truecheck(message: types.Message):
    if message["from"]["id"] in admin_ids:
        users = cursor.execute('SELECT id FROM users').fetchall()
        with open('users.txt', 'w') as f:
            for x in users:
                f.write(str(x[0])+'\n')
        checker = TrueChecker(bot_token)
        job = await checker.check_profile("users.txt")
        msg = await message.answer('Проверка запущена')
        progress = 0
        while int(progress) != 100:
            job = await checker.get_job_status(job.id)
            if job.progress != progress:
                await msg.edit_text(f'Проверено <b>{job.progress}%</b>')
            progress = job.progress
            sleep(3)
        username = (await dp.bot.me)['username']
        profile = await checker.get_profile(username)
        res = f'Пользователи\n - живы: {profile.users.active}\n - остановлены: {profile.users.stopped}\n - удалены: {profile.users.deleted}\n - отсутствуют: {profile.users.not_found}'
        await msg.delete()
        await message.answer(res)
        await checker.close()

@dp.message_handler(commands=['reset'], state='*')
async def send_reset_ad(message: types.Message):
    if message["from"]["id"] in admin_ids:
        with open('podp.txt', 'w', encoding='utf-8') as f:
            f.write('')
        global podp_text
        podp_text = ''
        await message.answer('Вы успешно сбросили сообщение')

@dp.message_handler(commands=['lang'], chat_type=types.ChatType.PRIVATE, state='*')
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
        if adv_text[0] == 'text':
            await message.answer(adv_text[1], reply_markup=adv_text[2], disable_web_page_preview=True, entities=adv_text[4])
        elif adv_text[0] == 'photo':
            await message.answer_photo(adv_text[3], caption=adv_text[1], reply_markup=adv_text[2], caption_entities=adv_text[4])
        elif adv_text[0] == 'gif':
            await message.answer_animation(adv_text[3], message.reply_markup, message.animation.file_id, caption_entities=adv_text[4])
    else:
        await message.answer('Вы не добавили сообщение')

@dp.message_handler(filters.Text(equals=["Отправить сообщение"], ignore_case=True), state=adv.menu)
async def adv_go(message: types.Message, state: FSMContext):
    global adv_text
    if adv_text != None:
        msg = await message.answer('<code>Началась рассылка</code>')
        users = cursor.execute("SELECT id from users").fetchall()
        num = 0
        for x in users:
            try:
                if adv_text[0] == 'text':
                    await bot.send_message(x[0], adv_text[1], reply_markup=adv_text[2], disable_web_page_preview=True, entities=adv_text[4])
                elif adv_text[0] == 'photo':
                    await bot.send_photo(x[0], adv_text[3], caption=adv_text[1], reply_markup=adv_text[2], caption_entities=adv_text[4])
                elif adv_text[0] == 'gif':
                    await bot.send_animation(x[0], adv_text[3], caption=adv_text[1], reply_markup=adv_text[2], caption_entities=adv_text[4])
                num += 1
            except:
                pass
            sleep(0.1)
        await msg.delete()
        await message.answer(f'Сообщение пришло <b>{num}</b> пользователям')
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

@dp.message_handler(content_types=['text', 'photo', 'animation'], state=adv.add)
async def notify_text(message: types.Message, state: FSMContext):
    global adv_text
    if 'photo' in message:
        adv_text = ['photo', message['caption'], message.reply_markup, message.photo[-1].file_id, message.caption_entities]
    elif 'animation' in message:
        adv_text = ['gif', message['caption'], message.reply_markup, message.animation.file_id, message.caption_entities]
    else:
        adv_text = ['text', message['text'], message.reply_markup, None, message.entities]
    await message.answer('Сообщение добавлено', reply_markup=keyboardmenu)
    await adv.menu.set()


@dp.callback_query_handler(lambda call: call.data.startswith('lang'), state='*')
async def inline_lang(callback_query: types.CallbackQuery):
    cht_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    cdata = callback_query.data
    lang = cdata.lstrip('lang/')
    try:
        cursor.execute(f'UPDATE users SET lang = "{lang}" WHERE id = {from_id}')
        sqlite.commit()
        await bot.edit_message_text(locale[lang]['lang'], cht_id, msg_id)
    except:
        pass
    return await callback_query.answer()

@dp.callback_query_handler(lambda call: call.data.startswith('id') or call.data.startswith('music'), state='*')
async def inline_music(callback_query: types.CallbackQuery):
    cht_type = callback_query.message.chat.type
    cht_id = callback_query['message']['chat']['id']
    from_id = callback_query['from']['id']
    msg_id = callback_query['message']['message_id']
    cdata = callback_query.data
    lang = lang_func(callback_query)
    msg = await bot.send_message(cht_id, '⏳')
    try:
        if cdata.startswith('id'):
            url = callback_query.data.lstrip('id/')
            playAddr = await api.url_free_music(url)
        elif cdata.startswith('music'):
            url = callback_query.data.lstrip('music/')
            playAddr = await api.url_paid_music(url)
        if playAddr in ['error', 'connerror', 'errorlink']: raise
        res = locale[lang]['result_song'].format(locale[lang]['bot_tag'], playAddr['cover'])
        audio = InputFile.from_url(url=playAddr['url'])
        await bot.send_chat_action(cht_id, 'upload_audio')
        await bot.send_audio(cht_id, audio, caption=res, title=playAddr['title'], performer=playAddr['author'], duration=playAddr['duration'], thumb=playAddr['cover'])
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
            await bot.send_message(cht_id, locale[lang]['error'])
    return await callback_query.answer()

@dp.message_handler()
async def send_ttdown(message: types.Message):
    try:
        lang = lang_func(message)
        try:
            if web_re.match(message.text) is not None:
                msg = await message.answer('⏳')
                link = web_re.findall(message.text)[0]
                if api_type == 'free':
                    id = red_re.findall(message.text)[0]
                    playAddr = await api.url_free(id)
                else:
                    playAddr = await api.url_paid(link)
                status = True
                if playAddr == 'errorlink': status = False
                elif playAddr in ['error', 'connerror']: raise
            elif mob_re.match(message.text) is not None:
                msg = await message.answer('⏳')
                link = mob_re.findall(message.text)[0]
                if api_type == 'free':
                    client = aiosonic.HTTPClient()
                    req = await client.get(message.text)
                    res = await req.text()
                    url_id = red_re.findall(res)[0]
                    playAddr = await api.url_free(url_id)
                else:
                    playAddr = await api.url_paid(link)
                status = True
                if playAddr == 'errorlink': status = False
                elif playAddr in ['error', 'connerror']: raise
        except:
            status = False


        if status is True:
            if api_type == 'paid':
                button_id = f'music/{playAddr["id"]}'
            else:
                button_id = f'id/{playAddr["id"]}'
                res = locale[lang]['result'].format(locale[lang]['bot_tag'], link)
                button_text = locale[lang]['get_sound']
            music = InlineKeyboardMarkup().add(InlineKeyboardButton(button_text, callback_data=button_id))
            await message.answer_chat_action('upload_video')
            vid = InputFile.from_url(url=playAddr['url'])
            cover = InputFile.from_url(url=playAddr['cover'])
            await message.answer_video(vid, caption=res, thumb=cover, height=playAddr['height'], width=playAddr['width'], duration=playAddr['duration']//1000, reply_markup=music)
            await msg.delete()
            try:
                if message.chat.type == 'private':
                    ltype = 'videos'
                else:
                    ltype = 'groups'
                cursor.execute(f'INSERT INTO {ltype} VALUES (?,?,?,?)', (message["chat"]["id"], tCurrent(), link, playAddr['url']))
                sqlite.commit()
                logging.info(f'{message["from"]["id"]}: {link}')
            except:
                logging.error(f'Неудалось записать в бд')
            if message.chat.type == 'private' and podp_text != '':
                await message.answer(podp_text)
        else:
            if message.chat.type == 'private':
                await msg.edit_text(locale[lang]['link_error'])
            else:
                await msg.delete()
            return
    except:
        try: await msg.delete()
        except: pass
        if message.chat.type == 'private':
            await message.answer(locale[lang]['error'])
        return

if __name__ == "__main__":

    web_re = re.compile(r'https?:\/\/www.tiktok.com\/@[^\s]+?\/video\/[0-9]+')
    mus_re = re.compile(r'https?://www.tiktok.com/music/[^\s]+')
    mob_re = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+')
    red_re = re.compile(r'https?:\/\/[^\s]+tiktok.com\/[^\s]+?\/([0-9]+)')

    api = ttapi(api_key)

    #Подключение sqlite
    sqlite = sqlite_init()
    cursor = sqlite.cursor()
    adv_text = None

    with open('api.txt', 'r', encoding='utf-8') as f:
            api_type = f.read()
    with open('podp.txt', 'r', encoding='utf-8') as f:
        podp_text = f.read()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(stats_log)
    scheduler.add_job(stats_log, "interval", seconds=300)
    scheduler.start()
    executor.start_polling(dp, skip_updates=True)
    sqlite.close()
    logging.info("Соединение с SQLite закрыто")