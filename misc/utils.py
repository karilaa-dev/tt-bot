from datetime import datetime
from time import time, ctime

from data.config import upd_chat, upd_id, locale
from data.loader import cursor, sqlite, bot


def tCurrent():
    return int(time())


def lang_func(usrid: int, usrlang: str, is_group: bool):
    try:
        try:
            if is_group:
                if usrlang in locale['langs']:
                    return usrlang
                return 'en'
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
    users = cursor.execute("SELECT COUNT(id) FROM users").fetchall()[0][0]
    videos = cursor.execute("SELECT COUNT(id) FROM videos").fetchall()[0][0]
    music = cursor.execute("SELECT COUNT(id) FROM music").fetchall()[0][0]
    groups = cursor.execute("SELECT COUNT(id) FROM groups").fetchall()[0][0]
    users24 = cursor.execute("SELECT COUNT(id) FROM users WHERE time >= ?",
                             (tnow - 86400,)).fetchall()[0][0]
    videos24 = cursor.execute("SELECT COUNT(id) FROM videos WHERE time >= ?",
                              (tnow - 86400,)).fetchall()[0][0]
    music24 = cursor.execute("SELECT COUNT(id) FROM music WHERE time >= ?",
                             (tnow - 86400,)).fetchall()[0][0]
    groups24 = cursor.execute("SELECT COUNT(id) FROM groups WHERE time >= ?",
                              (tnow - 86400,)).fetchall()[0][0]
    videos24u = cursor.execute("SELECT COUNT(DISTINCT(id)) FROM videos where time >= ?",
                               (tnow - 86400,)).fetchall()[0][0]
    return locale['stats'].format(users, music, videos, users24, music24,
                                  videos24, videos24u, groups, groups24)


async def stats_log():
    text = await bot_stats()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=upd_chat, message_id=upd_id, text=text)


async def backup_dp(chat_id: int):
    try:
        await bot.send_document(chat_id, open('sqlite.db', 'rb'),
                                caption=f'💾Backup\n<code>{datetime.utcnow()}</code>')
    except:
        pass
