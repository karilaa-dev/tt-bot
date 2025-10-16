import asyncio
import csv
import logging
from datetime import datetime
from io import StringIO

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func

from data.database import get_session
from data.db_service import (
    get_user_stats, get_user_videos, get_referral_stats,
    get_other_stats
)
from data.models import Users, Video, Music
from stats.misc import bot_stats, get_overall_stats, get_daily_stats, plot_async
from misc.utils import tCurrent, IsStatsAdmin

stats_router = Router(name=__name__)


class UserCheck(StatesGroup):
    search = State()


def stats_keyboard(chat_type='all', stats_time=86400):
    keyb = InlineKeyboardBuilder()
    times = ['⏰ 24h', '📅 Week', '📆 Month', '🌍 All']
    chat_types = ['👥 Users', '👥 Groups', '🌐 All']
    if stats_time == 0:
        times[3] = '✅ ' + times[3]
    elif stats_time == 2678400:
        times[2] = '✅ ' + times[2]
    elif stats_time == 604800:
        times[1] = '✅ ' + times[1]
    elif stats_time == 86400:
        times[0] = '✅ ' + times[0]

    if chat_type == 'all':
        chat_types[2] = '✅ ' + chat_types[2]
    elif chat_type == 'groups':
        chat_types[1] = '✅ ' + chat_types[1]
    elif chat_type == 'users':
        chat_types[0] = '✅ ' + chat_types[0]

    keyb.button(text=times[0], callback_data=f'stats:{chat_type}/86400')
    keyb.button(text=times[1], callback_data=f'stats:{chat_type}/604800')
    keyb.button(text=times[2], callback_data=f'stats:{chat_type}/2678400')
    keyb.button(text=times[3], callback_data=f'stats:{chat_type}/0')

    keyb.button(text=chat_types[0], callback_data=f'stats:users/{stats_time}')
    keyb.button(text=chat_types[1], callback_data=f'stats:groups/{stats_time}')
    keyb.button(text=chat_types[2], callback_data=f'stats:all/{stats_time}')

    keyb.button(text='🔄 Reload', callback_data=f'stats:{chat_type}/{stats_time}')
    keyb.button(text='🔙 Return', callback_data='stats_menu')

    keyb.adjust(4, 3, 2)
    return keyb.as_markup()


stats_graph_keyboard = InlineKeyboardBuilder()
stats_graph_keyboard.button(text='👥 Users Daily', callback_data='graph:users:daily')
stats_graph_keyboard.button(text='👥 Users Weekly', callback_data='graph:users:weekly')
stats_graph_keyboard.button(text='👥 Users Monthly', callback_data='graph:users:monthly')

stats_graph_keyboard.button(text='📹 Videos Daily', callback_data='graph:videos:daily')
stats_graph_keyboard.button(text='📹 Videos Weekly', callback_data='graph:videos:weekly')
stats_graph_keyboard.button(text='📹 Videos Monthly', callback_data='graph:videos:monthly')

stats_graph_keyboard.button(text='📊 Users Total', callback_data='graph:users:total')
stats_graph_keyboard.button(text='📊 Videos Total', callback_data='graph:videos:total')
stats_graph_keyboard.button(text='🔙 Return', callback_data='stats_menu')
stats_graph_keyboard.adjust(3, 3, 2, 1)
stats_graph_keyboard = stats_graph_keyboard.as_markup()

# Enhanced main menu keyboard with better organization
main_menu_keyboard = InlineKeyboardBuilder()
main_menu_keyboard.button(text='📊 Quick Stats', callback_data='stats_overall')
main_menu_keyboard.button(text='📈 Analytics', callback_data='stats_graphs')
main_menu_keyboard.button(text='🔍 User Search', callback_data='stats_user')
main_menu_keyboard.button(text='📋 Detailed View', callback_data='stats_detailed')
main_menu_keyboard.button(text='🗣 Referrals', callback_data='stats_referral')
main_menu_keyboard.button(text='🗃 Other Data', callback_data='stats_other')
main_menu_keyboard.button(text='❓ Help', callback_data='help_menu')
main_menu_keyboard.adjust(3, 3, 1)
main_menu_keyboard = main_menu_keyboard.as_markup()

# Keep the original stats_menu_keyboard for backward compatibility
# Enhanced main menu keyboard with better organization
main_menu_keyboard = InlineKeyboardBuilder()
main_menu_keyboard.button(text='📊 Quick Stats', callback_data='stats_overall')
main_menu_keyboard.button(text='📈 Analytics', callback_data='stats_graphs')
main_menu_keyboard.button(text='🔍 User Search', callback_data='stats_user')
main_menu_keyboard.button(text='📋 Detailed View', callback_data='stats_detailed')
main_menu_keyboard.button(text='🗣 Referrals', callback_data='stats_referral')
main_menu_keyboard.button(text='🗃 Other Data', callback_data='stats_other')
main_menu_keyboard.button(text='❓ Help', callback_data='help_menu')
main_menu_keyboard.adjust(3, 3, 1)
main_menu_keyboard = main_menu_keyboard.as_markup()

# Keep the original stats_menu_keyboard for backward compatibility
stats_menu_keyboard = InlineKeyboardBuilder()
stats_menu_keyboard.button(text='📊Overall Stats', callback_data='stats_overall')
stats_menu_keyboard.button(text='📋Detailed Stats', callback_data='stats_detailed')
stats_menu_keyboard.button(text='📈Graphs', callback_data='stats_graphs')
stats_menu_keyboard.button(text='👤User Stats', callback_data='stats_user')
stats_menu_keyboard.button(text='️🗣Referral Stats', callback_data='stats_referral')
stats_menu_keyboard.button(text='🗃Other Stats', callback_data='stats_other')
stats_menu_keyboard.adjust(3)
stats_menu_keyboard = stats_menu_keyboard.as_markup()

stats_return_keyboard = InlineKeyboardBuilder()
stats_return_keyboard.button(text='🔙 Return to Menu', callback_data='stats_menu')
stats_return_keyboard = stats_return_keyboard.as_markup()

stats_user_keyboard = InlineKeyboardBuilder()
stats_user_keyboard.button(text='🔍 Find Another User', callback_data='stats_user')
stats_user_keyboard.button(text='🔙 Return to Menu', callback_data='stats_menu')
stats_user_keyboard.adjust(1)
stats_user_keyboard = stats_user_keyboard.as_markup()


@stats_router.callback_query(F.data == 'stats_graphs')
async def stats_graphs(call: CallbackQuery):
    await call.message.edit_text('<b>📈Select Graph to check</b>\n<code>Generating graph can take time</code>',
                                 reply_markup=stats_graph_keyboard)


@stats_router.callback_query(F.data.startswith('graph:'))
async def stats_graph(call: CallbackQuery):
    graph_type, graph_time = call.data.split(':')[1:]
    temp = await call.message.edit_text('<code>Generating, please wait...</code>')
    try:
        time_now = tCurrent()
        graph_name = graph_type.capitalize() + " " + graph_time.capitalize()
        if graph_time == 'daily':
            period = time_now - 86400 * 2
            depth = '%Y-%m-%d %H'
        elif graph_time == 'weekly':
            period = time_now - 86400 * 8
            depth = '%Y-%m-%d %H'
        elif graph_time == 'monthly':
            period = time_now - 86400 * 32
            depth = '%Y-%m-%d'
        elif graph_time == 'total':
            async with await get_session() as db:
                if graph_type == 'users':
                    model = Users
                elif graph_type == 'videos':
                    model = Video
                else:
                    model = Music
                from sqlalchemy import select
                # Use the appropriate column name based on the model
                if graph_type == 'users':
                    time_column = model.registered_at
                else:
                    time_column = model.downloaded_at

                stmt = select(func.min(time_column))
                result = await db.execute(stmt)
                first_record = result.scalar()
                period = first_record if first_record is not None else time_now - 86400 * 365
            depth = '%Y-%m-%d'
        result = await plot_async(graph_name, depth, period, 'user_id != 0', graph_type)
        await call.message.answer_photo(BufferedInputFile(result, f'graph.png'))
        await temp.delete()
        await call.message.answer('<b>📈Select Graph to check</b>\n<code>Generating graph can take time</code>',
                                  reply_markup=stats_graph_keyboard)
    except Exception as e:
        logging.error(f"Error generating graph: {e}")
        await temp.edit_text('<code>Error generating graph. Please try again later.</code>')
        await asyncio.sleep(3)
        await temp.delete()
        await call.message.answer('<b>📈Select Graph to check</b>\n<code>Generating graph can take time</code>',
                                  reply_markup=stats_graph_keyboard)


@stats_router.callback_query(F.data == 'stats_overall')
async def stats_overall(call: CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    overall = await get_overall_stats()
    daily = await get_daily_stats()
    result = overall + "\n\n" + daily
    keyb = InlineKeyboardBuilder()
    keyb.button(text='🔄Reload', callback_data='stats_overall')
    keyb.button(text='↩️Return', callback_data='stats_menu')
    keyb.adjust(1)
    keyb = keyb.as_markup()
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@stats_router.callback_query(F.data == 'stats_user')
async def stats_user(call: CallbackQuery, state: FSMContext):
    msg = await call.message.edit_text('🔎Enter user id', reply_markup=stats_return_keyboard)
    await state.set_state(UserCheck.search)


@stats_router.message(UserCheck.search)
async def stats_user_search(message: Message, state: FSMContext):
    temp = await message.answer('<code>🔎Searching...</code>')
    user, videos_count, images_count = await get_user_stats(int(message.text))
    if not user:
        await temp.edit_text('❌User not found', reply_markup=stats_user_keyboard)
    else:
        result = '<b>👤User Stats</b>\n'
        result += f'┗ <b>ID</b>: <code>{user.user_id}</code>\n'
        result += f'┗ <b>Videos:</b> <code>{videos_count}</code>\n'
        result += f'    ┗ <b>Images:</b> <code>{images_count}</code>\n'
        result += f'┗ <b>Language:</b> <code>{user.lang}</code>\n'
        reg_time = datetime.fromtimestamp(user.registered_at)
        if user.link:
            result += f'┗ <b>Referral:</b> <code>{user.link}</code>\n'
        result += f'┗ <b>Registered:</b> <code>{reg_time.strftime("%d.%m.%Y %H:%M:%S")} UTC</code>\n'
        keyb = InlineKeyboardBuilder()
        keyb.button(text='📥Download video history', callback_data=f'user:{user.user_id}')
        keyb.button(text='👤Find another user', callback_data='stats_user')
        keyb.button(text='↩️Return', callback_data='stats_menu')
        keyb.adjust(1)
        keyb = keyb.as_markup()
        await temp.edit_text(result, reply_markup=keyb)
    await state.clear()


@stats_router.callback_query(F.data.startswith('user:'))
async def stats_user_download(call: CallbackQuery):
    user_id = call.data.split(':')[1]
    videos = await get_user_videos(int(user_id))
    if not videos:
        await call.answer('❌User has no videos')
    else:
        file = StringIO()
        writer = csv.writer(file)
        writer.writerow(['Time', 'Video'])
        for time, video in videos:
            time_date = str(datetime.fromtimestamp(time))
            writer.writerow([time_date, video])
        file.seek(0)
        await call.message.answer_document(BufferedInputFile(file.read().encode(), f'user_{user_id}.csv'),
                                           caption=f'📥User <code>{user_id}</code> video history')
        await call.answer()


@stats_router.callback_query(F.data == 'stats_referral')
async def stats_other(call: CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    result = '<b>🗣Referral Stats</b>\n'
    top_referrals = await get_referral_stats()
    for link, count in top_referrals:
        result += f'┗ {link}: <code>{count}</code>\n'
    keyb = InlineKeyboardBuilder()
    keyb.button(text='🔄Reload', callback_data='stats_referral')
    keyb.button(text='↩️Return', callback_data='stats_menu')
    keyb.adjust(1)
    keyb = keyb.as_markup()
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@stats_router.callback_query(F.data == 'stats_other')
async def stats_other(call: CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    result = '<b>🗃Other Stats</b>\n'
    file_mode_count, top_langs, top_users = await get_other_stats()
    result += f'<b>File mode users: <code>{file_mode_count}</code>\n</b>'
    result += 'Top languages:\n'
    for lang, count in top_langs:
        result += f'┗ {lang}: <code>{count}</code>\n'
    result += '<b>Top 10 users by downloads:</b>\n'
    for user_id, count in top_users:
        result += f'┗ {user_id}: <code>{count}</code>\n'
    keyb = InlineKeyboardBuilder()
    keyb.button(text='🔄Reload', callback_data='stats_other')
    keyb.button(text='↩️Return', callback_data='stats_menu')
    keyb.adjust(1)
    keyb = keyb.as_markup()
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@stats_router.callback_query(F.data == 'stats_detailed')
async def stats_detailed(call: CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    await temp.edit_text(await bot_stats(), reply_markup=stats_keyboard())


@stats_router.callback_query(F.data.startswith('stats:'))
async def stats_callback(call: CallbackQuery):
    group_type, stats_time = call.data.split(':')[1].split('/')
    stats_time = int(stats_time)
    await call.message.edit_text('Loading...')
    keyb = stats_keyboard(group_type, stats_time)
    await call.message.edit_text(await bot_stats(group_type, stats_time), reply_markup=keyb)
    await call.answer()


@stats_router.message(Command('start'), F.chat.type == 'private', IsStatsAdmin())
async def send_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "<b>🎉 Welcome to the Stats Bot!</b>\n\n"
        "📊 <i>Your comprehensive analytics dashboard</i>\n\n"
        "<b>Available features:</b>\n"
        "• 📈 View detailed statistics and graphs\n"
        "• 👤 Search and analyze user data\n"
        "• 🗣 Track referral performance\n"
        "• 📋 Export data in various formats\n\n"
        "<b>Quick start:</b>\n"
        "Use the buttons below or type /stats to access the main menu."
    )
    await message.answer(welcome_text, reply_markup=main_menu_keyboard)


@stats_router.message(Command('help'), F.chat.type == 'private', IsStatsAdmin())
async def send_help(message: Message, state: FSMContext):
    await state.clear()
    help_text = (
        "<b>❓ Stats Bot Help</b>\n\n"
        "<b>📋 Available Commands:</b>\n"
        "• /start - Welcome message and main menu\n"
        "• /stats - Open statistics menu\n"
        "• /help - Show this help message\n\n"
        "<b>🔍 Features:</b>\n"
        "• <b>📊 Quick Stats:</b> Overview of key metrics\n"
        "• <b>📈 Analytics:</b> Detailed graphs and trends\n"
        "• <b>🔍 User Search:</b> Find and analyze specific users\n"
        "• <b>📋 Detailed View:</b> In-depth statistics with filters\n"
        "• <b>🗣 Referrals:</b> Track referral performance\n"
        "• <b>🗃 Other Data:</b> Additional metrics and insights\n\n"
        "<b>💡 Tips:</b>\n"
        "• Use the time filters to view different periods\n"
        "• Export user data as CSV files\n"
        "• Generate graphs for visual analysis\n\n"
        "<i>Need assistance? Contact the bot administrator.</i>"
    )
    await message.answer(help_text, reply_markup=main_menu_keyboard)


@stats_router.callback_query(F.data == 'help_menu')
async def help_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    help_text = (
        "<b>❓ Stats Bot Help</b>\n\n"
        "<b>📋 Available Commands:</b>\n"
        "• /start - Welcome message and main menu\n"
        "• /stats - Open statistics menu\n"
        "• /help - Show this help message\n\n"
        "<b>🔍 Features:</b>\n"
        "• <b>📊 Quick Stats:</b> Overview of key metrics\n"
        "• <b>📈 Analytics:</b> Detailed graphs and trends\n"
        "• <b>🔍 User Search:</b> Find and analyze specific users\n"
        "• <b>📋 Detailed View:</b> In-depth statistics with filters\n"
        "• <b>🗣 Referrals:</b> Track referral performance\n"
        "• <b>🗃 Other Data:</b> Additional metrics and insights\n\n"
        "<b>💡 Tips:</b>\n"
        "• Use the time filters to view different periods\n"
        "• Export user data as CSV files\n"
        "• Generate graphs for visual analysis\n\n"
        "<i>Need assistance? Contact the bot administrator.</i>"
    )
    await call.message.edit_text(help_text, reply_markup=main_menu_keyboard)


@stats_router.message(Command('stats'), F.chat.type == 'private', IsStatsAdmin())
async def send_stats(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('<b>📊Stats Menu</b>', reply_markup=stats_menu_keyboard)


@stats_router.callback_query(F.data == 'stats_menu')
async def stats_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text('<b>📊Stats Menu</b>', reply_markup=stats_menu_keyboard)
