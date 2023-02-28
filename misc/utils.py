import logging
from datetime import datetime
from time import time, ctime

from data.config import upd_chat, upd_id, locale, logs
from data.loader import cursor, sqlite, bot


def tCurrent():
    return int(time())


def lang_func(usrid: int, usrlang: str):
    try:
        try:
            lang_req = cursor.execute("SELECT lang FROM users WHERE id = ?",
                                      (usrid,)).fetchone()[0]
        except:
            lang_req = None
        if lang_req is not None:
            lang = lang_req
        else:
            lang = usrlang
            if lang not in locale['langs']:
                return 'en'
            cursor.execute('UPDATE users SET lang = ? WHERE id = ?',
                           (lang, usrid))
            sqlite.commit()
        return lang
    except:
        return 'en'


def bot_stats(chat_type='all', stats_time=0):
    if stats_time == 0:
        period = 0
    else:
        period = tCurrent() - stats_time
    if chat_type == 'all':
        chat_type = '!='
    elif chat_type == 'groups':
        chat_type = '<'
    elif chat_type == 'users':
        chat_type = '>'

    chats = cursor.execute(f"SELECT COUNT(id) FROM users WHERE id {chat_type} 0 and time > ?", (period,)).fetchone()[0]

    vid = cursor.execute(f"SELECT COUNT(id) FROM videos WHERE id {chat_type} 0 and time > ?", (period,)).fetchone()[0]
    vid_img = cursor.execute(f"SELECT COUNT(id) FROM videos WHERE id {chat_type} 0 and time > ? and is_images = 1",
                             (period,)).fetchone()[0]

    vid_u = cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM videos WHERE id {chat_type} 0 and time > ?",
                               (period,)).fetchone()[0]
    vid_img_u = cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM videos WHERE id {chat_type} 0 and time > ? and is_images = 1",
                           (period,)).fetchone()[0]

    music = cursor.execute(f"SELECT COUNT(id) FROM users WHERE id {chat_type} 0 and time > ?", (period,)).fetchone()[0]
    music_u = cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM users WHERE id {chat_type} 0 and time > ?", (period,)).fetchone()[0]

    text = \
f'''Chats: <b>{chats}</b>
Music: <b>{music}</b>
┗ Unique: <b>{music_u}</b>
Videos: <b>{vid}</b>
┗ Images: <b>{vid_img}</b>
Unique videos: <b>{vid_u}</b>
┗ Images: <b>{vid_img_u}</b>'''

    return text


async def stats_log():
    text = bot_stats()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=upd_chat, message_id=upd_id, text=text)


async def backup_dp(chat_id: int):
    try:
        await bot.send_document(chat_id, open('sqlite.db', 'rb'),
                                caption=f'#Backup💾\n<code>{datetime.utcnow()}</code>')
    except:
        pass


async def start_manager(chat_id, message, lang):
    if message.get_args() is not None:
        args = message.get_args().lower()
    else:
        args = ''
    if args == '':
        args = None
    cursor.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)',
                   (chat_id, tCurrent(), lang, args, 0))
    sqlite.commit()
    username = ''
    if message.chat.username is not None:
        username = f'@{message.chat.username}\n'
    text = f'<b><a href="tg://user?id={chat_id}">{message.chat.full_name}</a></b>' \
           f'\n{username}<code>{chat_id}</code>\n<i>{args or ""}</i>'
    await bot.send_message(logs, text)
    username = username.replace('\n', ' ')
    logging.info(f'{message.chat.full_name} {username}{chat_id} {args or ""}')
    if chat_id > 0:
        start_text = locale[lang]['start'] + locale[lang]['group_info']
    else:
        start_text = locale[lang]['start']
    await message.answer(start_text)
    await message.answer(locale[lang]['lang_start'])
