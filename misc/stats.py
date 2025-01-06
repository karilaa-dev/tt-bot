import asyncio
from datetime import datetime
from io import BytesIO
from time import ctime

import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import text, func

from data.config import config
from data.database import db_session
from data.loader import bot
from data.models import User, Video, Music
from misc.utils import tCurrent


def bot_stats(chat_type='all', stats_time=86400):
    with db_session() as db:
        if stats_time == 0:
            period = 0
        else:
            period = tCurrent() - stats_time

        # Build filter conditions
        if chat_type == 'all':
            user_filter = User.id != 0
            video_filter = Video.id != 0
            music_filter = Music.id != 0
        elif chat_type == 'groups':
            user_filter = User.id < 0
            video_filter = Video.id < 0
            music_filter = Music.id < 0
        else:  # users
            user_filter = User.id > 0
            video_filter = Video.id > 0
            music_filter = Music.id > 0

        # Add time filter
        if period > 0:
            user_filter = user_filter & (User.time > period)
            video_filter = video_filter & (Video.time > period)
            music_filter = music_filter & (Music.time > period)

        # Get stats
        chats = db.query(func.count(User.id)).filter(user_filter).scalar()

        vid = db.query(func.count(Video.id)).filter(video_filter).scalar()
        vid_img = db.query(func.count(Video.id)).filter(video_filter & (Video.is_images == 1)).scalar()

        vid_u = db.query(func.count(func.distinct(Video.id))).filter(video_filter).scalar()
        vid_img_u = db.query(func.count(func.distinct(Video.id))).filter(video_filter & (Video.is_images == 1)).scalar()

        music = db.query(func.count(Music.video)).filter(music_filter).scalar()
        music_u = db.query(func.count(func.distinct(Music.id))).filter(music_filter).scalar()

    text = \
        f'''Chats: <b>{chats}</b>
Music: <b>{music}</b>
┗ Unique: <b>{music_u}</b>
Videos: <b>{vid}</b>
┗ Unique: <b>{vid_u}</b>
┗ Images: <b>{vid_img}</b>
    ┗ Unique: <b>{vid_img_u}</b>'''

    return text


def plot_users_grouped(days, amounts, graph_name):
    plt.figure(figsize=(18, 9))
    
    if not days or not amounts:
        plt.text(0.5, 0.5, 'No data available for this period', 
                horizontalalignment='center', verticalalignment='center',
                transform=plt.gca().transAxes, fontsize=14)
        plt.grid(False)
    else:
        plt.plot(days, amounts, linestyle="-")

        marker_days = [day for day, amount in zip(days, amounts) if amount > 0]
        marker_amounts = [amount for amount in amounts if amount > 0]
        if marker_days and marker_amounts:
            plt.scatter(marker_days, marker_amounts, c='b')

        plt.xlabel("Date")
        plt.ylabel("Number of Users")
        plt.title(graph_name)
        plt.xticks(rotation=45)
        plt.grid()

    buffer = BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.clf()
    return buffer.getvalue()


def plot_user_graph(graph_name, depth, period, id_condition, table_name):
    time_now = tCurrent()
    last_day = time_now // 86400 * 86400

    with db_session() as db:
        if table_name == 'users':
            table = User
        elif table_name == 'videos':
            table = Video
        else:
            table = Music

        query = db.query(table.time).filter(
            table.time <= last_day,
            table.time > period,
            text(id_condition)
        )
        
        df = pd.read_sql(query.statement, db.bind)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df_grouped = df.groupby(df["time"].dt.strftime(depth)).size().reset_index(name="count")

    start_date = datetime.fromtimestamp(period)
    end_date = datetime.fromtimestamp(last_day)
    date_range = pd.date_range(start=start_date, end=end_date, freq='h').strftime(depth)
    df_date_range = pd.DataFrame(date_range, columns=["time"])

    df_merged = df_date_range.merge(df_grouped, on="time", how="left").fillna(0)

    # Remove rows with zero counts from the start of the DataFrame
    df_merged = df_merged[df_merged["count"].ne(0)].reset_index(drop=True)

    day_amount_list = [(datetime.strptime(row[0], depth), row[1]) for row in df_merged.to_records(index=False)]
    
    if not day_amount_list:
        # Create a simple graph showing "No data"
        plt.figure(figsize=(18, 9))
        plt.text(0.5, 0.5, 'No data available for this period', 
                horizontalalignment='center', verticalalignment='center',
                transform=plt.gca().transAxes, fontsize=14)
        plt.grid(False)
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plt.clf()
        return buffer.getvalue()
    
    days, amounts = zip(*day_amount_list)
    days = [datetime.strptime(day.strftime(depth), depth) for day in days]

    return plot_users_grouped(days, amounts, graph_name)


async def plot_async(graph_name, depth, period, id_condition, table):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: plot_user_graph(graph_name, depth, period, id_condition, table))


async def get_stats_overall():
    result = '<b>📊Overall Stats</b>\n'
    result += bot_stats(chat_type='users', stats_time=0)
    result += '\n<b>Groups</b>\n'
    result += bot_stats(chat_type='groups', stats_time=0)
    result += '\n\n<b>In 24 hours</b>\n'
    result += bot_stats(chat_type='users', stats_time=86400)
    result += '\n<b>Groups</b>\n'
    result += bot_stats(chat_type='groups', stats_time=86400)
    return result


async def stats_log():
    text = await get_stats_overall()
    text += f'\n\n<code>{ctime(tCurrent())[:-5]}</code>'
    await bot.edit_message_text(chat_id=config["logs"]["stats_chat"], message_id=config["logs"]["stats_message_id"], text=text)
