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


async def bot_stats():
    tnow = tCurrent()
    users = cursor.execute("SELECT COUNT(id) FROM users WHERE id > 0").fetchall()[0][0]
    groups = cursor.execute("SELECT COUNT(id) FROM users WHERE id < 0").fetchall()[0][0]
    videos = cursor.execute("SELECT COUNT(id) FROM videos WHERE id > 0").fetchall()[0][0]
    videos_groups = cursor.execute("SELECT COUNT(id) FROM videos WHERE id < 0").fetchall()[0][0]
    music = cursor.execute("SELECT COUNT(id) FROM music").fetchall()[0][0]

    old_24 = tnow - 86400

    users24 = cursor.execute("SELECT COUNT(id) FROM users WHERE time >= ? and id > 0",
                             (old_24,)).fetchall()[0][0]
    groups24 = cursor.execute("SELECT COUNT(id) FROM users WHERE time >= ? and id < 0",
                              (old_24,)).fetchall()[0][0]
    music24 = cursor.execute("SELECT COUNT(id) FROM music WHERE time >= ?",
                             (old_24,)).fetchall()[0][0]
    videos24 = cursor.execute("SELECT COUNT(id) FROM videos WHERE time >= ? and id > 0",
                              (old_24,)).fetchall()[0][0]
    videos24u = cursor.execute("SELECT COUNT(DISTINCT(id)) FROM videos where time >= ? and id > 0",
                               (old_24,)).fetchall()[0][0]
    videos_groups24 = cursor.execute("SELECT COUNT(id) FROM videos WHERE time >= ? and id < 0",
                                     (old_24,)).fetchall()[0][0]
    videos_groups24u = cursor.execute("SELECT COUNT(DISTINCT(id)) FROM videos where time >= ? and id < 0",
                                      (old_24,)).fetchall()[0][0]
    return locale['stats'].format(users, groups, videos, videos_groups, music, users24, groups24, music24, videos24,
                                  videos24u, videos_groups24, videos_groups24u)


async def stats_log():
    text = await bot_stats()
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
    await message.answer(locale[lang]['start'])
    await message.answer(locale[lang]['lang_start'])
