import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func

from data.config import config
from data.database import get_session
from data.models import Users, Video, Music
from misc.utils import tCurrent
from stats.loader import bot


async def bot_stats(chat_type='all', stats_time=86400):
    async with await get_session() as db:
        if stats_time == 0:
            period = 0
        else:
            period = tCurrent() - stats_time

        # Build filter conditions
        if chat_type == 'all':
            user_filter = Users.user_id != 0
            video_filter = Video.user_id != 0
            music_filter = Music.user_id != 0
        elif chat_type == 'groups':
            user_filter = Users.user_id < 0
            video_filter = Video.user_id < 0
            music_filter = Music.user_id < 0
        else:  # users
            user_filter = Users.user_id > 0
            video_filter = Video.user_id > 0
            music_filter = Music.user_id > 0

        # Add time filter
        if period > 0:
            user_filter = user_filter & (Users.registered_at > period)
            video_filter = video_filter & (Video.downloaded_at > period)
            music_filter = music_filter & (Music.downloaded_at > period)

        from sqlalchemy import select

        # Get stats
        stmt = select(func.count(Users.user_id)).where(user_filter)
        result = await db.execute(stmt)
        chats = result.scalar()

        stmt = select(func.count(Video.user_id)).where(video_filter)
        result = await db.execute(stmt)
        vid = result.scalar()

        stmt = select(func.count(Video.user_id)).where(video_filter & (Video.is_images == True))
        result = await db.execute(stmt)
        vid_img = result.scalar()

        stmt = select(func.count(func.distinct(Video.user_id))).where(video_filter)
        result = await db.execute(stmt)
        vid_u = result.scalar()

        stmt = select(func.count(func.distinct(Video.user_id))).where(video_filter & (Video.is_images == True))
        result = await db.execute(stmt)
        vid_img_u = result.scalar()

        stmt = select(func.count(Music.video_id)).where(music_filter)
        result = await db.execute(stmt)
        music = result.scalar()

        stmt = select(func.count(func.distinct(Music.user_id))).where(music_filter)
        result = await db.execute(stmt)
        music_u = result.scalar()

    text = \
        f'''Chats: <b>{chats}</b>
Music: <b>{music}</b>
┗ Unique: <b>{music_u}</b>
Videos: <b>{vid}</b>
┗ Unique: <b>{vid_u}</b>
┗ Images: <b>{vid_img}</b>
    ┗ Unique: <b>{vid_img_u}</b>'''

    return text





async def get_overall_stats():
    result = '<b>📊Overall Stats</b>\n'
    result += await bot_stats(chat_type='users', stats_time=0)
    result += '\n<b>Groups</b>\n'
    result += await bot_stats(chat_type='groups', stats_time=0)
    return result


async def get_daily_stats():
    result = '<b>📊Last 24 Hours</b>\n'
    result += await bot_stats(chat_type='users', stats_time=86400)
    result += '\n<b>Groups</b>\n'
    result += await bot_stats(chat_type='groups', stats_time=86400)
    return result


def get_formatted_timestamp():
    ts = datetime.fromtimestamp(tCurrent())
    prague_time = ts.astimezone(ZoneInfo("Europe/Prague")).strftime("%H:%M:%S / %d %B %Y")
    la_time = ts.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%I:%M:%S %p / %d %B %Y")
    return f'\n\n<code>🇨🇿 {prague_time}\n🇺🇸 {la_time}</code>'


async def update_overall_stats():
    overall_text = await get_overall_stats()
    await bot.edit_message_text(
        chat_id=config["logs"]["stats_chat"],
        message_id=config["logs"]["stats_message_id"],
        text=overall_text + get_formatted_timestamp()
    )


async def update_daily_stats():
    daily_text = await get_daily_stats()
    await bot.edit_message_text(
        chat_id=config["logs"]["stats_chat"],
        message_id=config["logs"]["daily_stats_message_id"],
        text=daily_text + get_formatted_timestamp()
    )
