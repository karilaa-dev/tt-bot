import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO


import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import text, func

from data.config import config
from data.database import get_session
from data.loader import bot
from data.models import Users, Video, Music
from misc.utils import tCurrent


async def bot_stats(chat_type='all', stats_time=86400):
    async with await get_session() as db:
        if stats_time == 0:
            period = 0
        else:
            period = tCurrent() - stats_time

        # Build filter conditions
        if chat_type == 'all':
            user_filter = Users.id != 0
            video_filter = Video.id != 0
            music_filter = Music.id != 0
        elif chat_type == 'groups':
            user_filter = Users.id < 0
            video_filter = Video.id < 0
            music_filter = Music.id < 0
        else:  # users
            user_filter = Users.id > 0
            video_filter = Video.id > 0
            music_filter = Music.id > 0

        # Add time filter
        if period > 0:
            user_filter = user_filter & (Users.registered_at > period)
            video_filter = video_filter & (Video.downloaded_at > period)
            music_filter = music_filter & (Music.downloaded_at > period)

        from sqlalchemy import select

        # Get stats
        stmt = select(func.count(Users.id)).where(user_filter)
        result = await db.execute(stmt)
        chats = result.scalar()

        stmt = select(func.count(Video.id)).where(video_filter)
        result = await db.execute(stmt)
        vid = result.scalar()

        stmt = select(func.count(Video.id)).where(video_filter & (Video.is_images is True))
        result = await db.execute(stmt)
        vid_img = result.scalar()

        stmt = select(func.count(func.distinct(Video.id))).where(video_filter)
        result = await db.execute(stmt)
        vid_u = result.scalar()

        stmt = select(func.count(func.distinct(Video.id))).where(video_filter & (Video.is_images is True))
        result = await db.execute(stmt)
        vid_img_u = result.scalar()

        stmt = select(func.count(Music.video)).where(music_filter)
        result = await db.execute(stmt)
        music = result.scalar()

        stmt = select(func.count(func.distinct(Music.id))).where(music_filter)
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


async def plot_user_graph(graph_name, depth, period, id_condition, table_name):
    time_now = tCurrent()
    last_day = time_now // 86400 * 86400

    # Get the appropriate table
    if table_name == 'users':
        table = Users
    elif table_name == 'videos':
        table = Video
    else:
        table = Music

    # Get data from database
    async with await get_session() as db:
        from sqlalchemy import select
        # Use the appropriate column name based on the table
        time_column = table.registered_at if table_name == 'users' else table.downloaded_at
        stmt = select(time_column).where(
            time_column <= last_day,
            time_column > period,
            text(id_condition)
        )
        result = await db.execute(stmt)
        times = [r[0] for r in result.all()]

    # If no data, return empty graph
    if not times:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: plot_users_grouped([], [], graph_name))

    # Process data
    df = pd.DataFrame({"time": times})
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df_grouped = df.groupby(df["time"].dt.strftime(depth)).size().reset_index(name="count")

    # Create date range
    start_date = datetime.fromtimestamp(period)
    end_date = datetime.fromtimestamp(last_day)
    date_range = pd.date_range(start=start_date, end=end_date, freq='h').strftime(depth)
    df_date_range = pd.DataFrame(date_range, columns=["time"])

    # Merge data
    df_merged = df_date_range.merge(df_grouped, on="time", how="left").fillna(0)
    df_merged = df_merged[df_merged["count"].ne(0)].reset_index(drop=True)

    # Convert to list of tuples
    day_amount_list = [(datetime.strptime(row[0], depth), row[1]) for row in df_merged.to_records(index=False)]
    if not day_amount_list:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: plot_users_grouped([], [], graph_name))

    # Prepare data for plotting
    days, amounts = zip(*day_amount_list)
    days = [datetime.strptime(day.strftime(depth), depth) for day in days]

    # Run plotting in a thread
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: plot_users_grouped(days, amounts, graph_name))


async def plot_async(graph_name, depth, period, id_condition, table):
    try:
        # plot_user_graph already returns the final buffer
        return await plot_user_graph(graph_name, depth, period, id_condition, table)
    except Exception as e:
        logging.error(f"Error in plot_async: {e}")
        raise


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
