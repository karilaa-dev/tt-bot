import asyncio
import sqlite3
from datetime import datetime
from io import BytesIO
from time import ctime

import matplotlib.pyplot as plt
import pandas as pd

from data.config import config
from data.loader import cursor, bot
from misc.utils import tCurrent


def bot_stats(chat_type='all', stats_time=86400):
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
    vid_img_u = \
        cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM videos WHERE id {chat_type} 0 and time > ? and is_images = 1",
                       (period,)).fetchone()[0]

    music = cursor.execute(f"SELECT COUNT(id) FROM music WHERE id {chat_type} 0 and time > ?", (period,)).fetchone()[0]
    music_u = \
        cursor.execute(f"SELECT COUNT(DISTINCT(id)) FROM music WHERE id {chat_type} 0 and time > ?",
                       (period,)).fetchone()[
            0]

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
    plt.plot(days, amounts, linestyle="-")

    marker_days = [day for day, amount in zip(days, amounts) if amount > 0]
    marker_amounts = [amount for amount in amounts if amount > 0]
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


def plot_user_graph(graph_name, depth, period, id_condition, table):
    time_now = tCurrent()
    last_day = time_now // 86400 * 86400

    query = f"""SELECT time FROM {table} WHERE
                time <= {last_day} and
                time > {period} and
                {id_condition}"""

    df = pd.read_sql_query(query, sqlite3.connect(config["bot"]["db_name"]))
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df_grouped = df.groupby(df["time"].dt.strftime(depth)).size().reset_index(name="count")

    start_date = datetime.fromtimestamp(period)
    end_date = datetime.fromtimestamp(last_day)
    date_range = pd.date_range(start=start_date, end=end_date, freq='H').strftime(depth)
    df_date_range = pd.DataFrame(date_range, columns=["time"])

    df_merged = df_date_range.merge(df_grouped, on="time", how="left").fillna(0)

    # Remove rows with zero counts from the start of the DataFrame
    df_merged = df_merged[df_merged["count"].ne(0)].reset_index(drop=True)

    day_amount_list = [(datetime.strptime(row[0], depth), row[1]) for row in df_merged.to_records(index=False)]
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
