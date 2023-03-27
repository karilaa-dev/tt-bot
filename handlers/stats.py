import csv
from datetime import datetime
from io import BytesIO, StringIO

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from data.config import admin_ids, second_ids
from data.loader import cursor, dp
from misc.stats import bot_stats, plot_user_graph, get_stats_overall, plot_async
from misc.utils import tCurrent


class UserCheck(StatesGroup):
    search = State()


def stats_keyboard(chat_type='all', stats_time=0):
    keyb = InlineKeyboardMarkup()
    times = ['24h', 'Week', 'Month', 'All']
    chat_types = ['Users', 'Groups', 'All']
    if stats_time == 0:
        times[3] = '✅' + times[3]
    elif stats_time == 2678400:
        times[2] = '✅' + times[2]
    elif stats_time == 604800:
        times[1] = '✅' + times[1]
    elif stats_time == 86400:
        times[0] = '✅' + times[0]

    if chat_type == 'all':
        chat_types[2] = '✅' + chat_types[2]
    elif chat_type == 'groups':
        chat_types[1] = '✅' + chat_types[1]
    elif chat_type == 'users':
        chat_types[0] = '✅' + chat_types[0]

    keyb.row(InlineKeyboardButton(times[0], callback_data=f'stats:{chat_type}/86400'),
             InlineKeyboardButton(times[1], callback_data=f'stats:{chat_type}/604800'),
             InlineKeyboardButton(times[2], callback_data=f'stats:{chat_type}/2678400'),
             InlineKeyboardButton(times[3], callback_data=f'stats:{chat_type}/0'))

    keyb.row(InlineKeyboardButton(chat_types[0], callback_data=f'stats:users/{stats_time}'),
             InlineKeyboardButton(chat_types[1], callback_data=f'stats:groups/{stats_time}'),
             InlineKeyboardButton(chat_types[2], callback_data=f'stats:all/{stats_time}'))

    keyb.add(InlineKeyboardButton('🔄Reload', callback_data=f'stats:{chat_type}/{stats_time}'))
    keyb.add(InlineKeyboardButton('↩Return', callback_data='stats_menu'))
    return keyb


stats_graph_keyboard = InlineKeyboardMarkup()
stats_graph_keyboard.row(InlineKeyboardButton('👥Daily', callback_data='graph:users:daily'),
                         InlineKeyboardButton('👥Weekly', callback_data='graph:users:weekly'),
                         InlineKeyboardButton('👥Monthly', callback_data='graph:users:monthly'),
                         InlineKeyboardButton('👥Total', callback_data='graph:users:total'))
stats_graph_keyboard.row(InlineKeyboardButton('📹Daily', callback_data='graph:videos:daily'),
                         InlineKeyboardButton('📹Weekly', callback_data='graph:videos:weekly'),
                         InlineKeyboardButton('📹Monthly', callback_data='graph:videos:monthly'),
                         InlineKeyboardButton('📹Total', callback_data='graph:videos:total'))
stats_graph_keyboard.add(InlineKeyboardButton('↩Return', callback_data='stats_menu'))

stats_menu_keyboard = InlineKeyboardMarkup()
stats_menu_keyboard.row(InlineKeyboardButton('📊Overall Stats', callback_data='stats_overall'),
                        InlineKeyboardButton('📋Detailed Stats', callback_data='stats_detailed'),
                        InlineKeyboardButton('📈Graphs', callback_data='stats_graphs'))
stats_menu_keyboard.row(InlineKeyboardButton('👤User Stats', callback_data='stats_user'),
                        InlineKeyboardButton('️🗣Referral Stats', callback_data='stats_referral'),
                        InlineKeyboardButton('🗃Other Stats', callback_data='stats_other'))

stats_return_keyboard = InlineKeyboardMarkup()
stats_return_keyboard.add(InlineKeyboardButton('↩Return', callback_data='stats_menu'))

stats_user_keyboard = InlineKeyboardMarkup()
stats_user_keyboard.add(InlineKeyboardButton('👤Find another user', callback_data='stats_user'))
stats_user_keyboard.add(InlineKeyboardButton('↩Return', callback_data='stats_menu'))


@dp.callback_query_handler(lambda c: c.data == 'stats_graphs')
async def stats_graphs(call: types.CallbackQuery):
    await call.message.edit_text('<b>📈Select Graph to check</b>\n<code>Generating graph can take time</code>',
                                 reply_markup=stats_graph_keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('graph:'))
async def stats_graph(call: types.CallbackQuery):
    graph_type, graph_time = call.data.split(':')[1:]
    temp = await call.message.edit_text('<code>Generating, please wait...</code>')
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
        period = cursor.execute(f"SELECT time FROM {graph_type} ORDER BY time ASC LIMIT 1").fetchone()[0]
        depth = '%Y-%m-%d'
    result = await plot_async(graph_name, depth, period, 'id != 0', graph_type)
    await call.message.answer_photo(result)
    await temp.delete()
    await call.message.answer('<b>📈Select Graph to check</b>\n<code>Generating graph can take time</code>',
                              reply_markup=stats_graph_keyboard)


@dp.callback_query_handler(lambda c: c.data == 'stats_overall')
async def stats_overall(call: types.CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    result = get_stats_overall()
    keyb = InlineKeyboardMarkup()
    keyb.add(InlineKeyboardButton('🔄Reload', callback_data='stats_overall_update'))
    keyb.add(InlineKeyboardButton('↩️Return', callback_data='stats_menu'))
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@dp.callback_query_handler(lambda c: c.data == 'stats_user')
async def stats_user(call: types.CallbackQuery):
    msg = await call.message.edit_text('🔎Enter user id', reply_markup=stats_return_keyboard)
    await UserCheck.search.set()


@dp.message_handler(state=UserCheck.search)
async def stats_user_search(message: types.Message, state: FSMContext):
    temp = await message.answer('<code>🔎Searching...</code>')
    req = cursor.execute('SELECT * FROM users WHERE id = ?', (message.text,)).fetchone()
    if req is None:
        await temp.edit_text('❌User not found', reply_markup=stats_user_keyboard)
    else:
        result = '<b>👤User Stats</b>\n'
        result += f'┗ <b>ID</b>: <code>{req[0]}</code>\n'
        videos = cursor.execute('SELECT COUNT(1) FROM videos WHERE id = ?', (req[0],)).fetchone()[0]
        result += f'┗ <b>Videos:</b> <code>{videos}</code>\n'
        videos_images = \
        cursor.execute('SELECT COUNT(1) FROM videos WHERE id = ? AND is_images = 1', (req[0],)).fetchone()[0]
        result += f'    ┗ <b>Images:</b> <code>{videos_images}</code>\n'
        result += f'┗ <b>Language:</b> <code>{req[2]}</code>\n'
        reg_time = datetime.fromtimestamp(req[1])
        if req[3] is not None:
            result += f'┗ <b>Referral:</b> <code>{req[3]}</code>\n'
        result += f'┗ <b>Registered:</b> <code>{reg_time.strftime("%d.%m.%Y %H:%M:%S")} UTC</code>\n'
        keyb = InlineKeyboardMarkup()
        keyb.add(InlineKeyboardButton('📥Download video history', callback_data=f'user:{req[0]}'))
        keyb.add(InlineKeyboardButton('👤Find another user', callback_data='stats_user'))
        keyb.add(InlineKeyboardButton('↩️Return', callback_data='stats_menu'))
        await temp.edit_text(result, reply_markup=keyb)
    await state.finish()


@dp.callback_query_handler(lambda c: c.data.startswith('user:'))
async def stats_user_download(call: types.CallbackQuery):
    user_id = call.data.split(':')[1]
    videos = cursor.execute('SELECT time, video FROM videos WHERE id = ?', (user_id,)).fetchall()
    if len(videos) == 0:
        await call.answer('❌User has no videos')
    else:
        file = StringIO()
        writer = csv.writer(file)
        writer.writerow(['Time', 'Video'])
        for video in videos:
            time_date = str(datetime.fromtimestamp(video[0]))
            video = str(video[1])
            writer.writerow([time_date, video])
        file.seek(0)
        bytes_file = BytesIO(file.read().encode())
        bytes_file.name = f'user_{user_id}.csv'
        await call.message.answer_document(bytes_file, caption=f'📥User <code>{user_id}</code> video history')
        await call.answer()


@dp.callback_query_handler(lambda c: c.data == 'stats_referral')
async def stats_other(call: types.CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    result = '<b>🗣Referral Stats</b>\n'
    top_referrals = cursor.execute(
        'SELECT link, COUNT(link) AS cnt FROM users GROUP BY link ORDER BY cnt DESC LIMIT 10').fetchall()
    for referral in top_referrals:
        if referral[0] is not None:
            result += f'┗ {referral[0]}: <code>{referral[1]}</code>\n'
    keyb = InlineKeyboardMarkup()
    keyb.add(InlineKeyboardButton('🔄Reload', callback_data='stats_referral_update'))
    keyb.add(InlineKeyboardButton('↩️Return', callback_data='stats_menu'))
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@dp.callback_query_handler(lambda c: c.data == 'stats_other')
async def stats_other(call: types.CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    result = '<b>🗃Other Stats</b>\n'
    file_mode = cursor.execute('SELECT COUNT(id) FROM users WHERE file_mode = 1').fetchone()[0]
    result += f'<b>File mode users: <code>{file_mode}</code>\n</b>'
    top_langs = cursor.execute('SELECT lang, COUNT(lang) AS cnt FROM users GROUP BY lang ORDER BY cnt DESC').fetchall()
    result += 'Top languages:\n'
    for lang in top_langs:
        result += f'┗ {lang[0]}: <code>{lang[1]}</code>\n'
    top_10_users = cursor.execute(
        'SELECT id, COUNT(id) AS cnt FROM videos GROUP BY id ORDER BY cnt DESC LIMIT 10').fetchall()
    result += '<b>Top 10 users by downloads:</b>\n'
    for user in top_10_users:
        result += f'┗ {user[0]}: <code>{user[1]}</code>\n'
    keyb = InlineKeyboardMarkup()
    keyb.add(InlineKeyboardButton('🔄Reload', callback_data='stats_other_update'))
    keyb.add(InlineKeyboardButton('↩️Return', callback_data='stats_menu'))
    try:
        await temp.edit_text(result, reply_markup=keyb)
    except:
        await call.answer('⚠Nothing to update')


@dp.callback_query_handler(lambda c: c.data == 'stats_detailed')
async def stats_detailed(call: types.CallbackQuery):
    temp = await call.message.edit_text('<code>Loading...</code>')
    await temp.edit_text(bot_stats(), reply_markup=stats_keyboard())


@dp.callback_query_handler(lambda c: c.data.startswith('stats:'))
async def stats_callback(call: types.CallbackQuery):
    group_type, stats_time = call.data.split(':')[1].split('/')
    stats_time = int(stats_time)
    await call.message.edit_text('Loading...')
    keyb = stats_keyboard(group_type, stats_time)
    await call.message.edit_text(bot_stats(group_type, stats_time), reply_markup=keyb)
    await call.answer()


@dp.message_handler(commands=["stats"], state='*')
async def send_stats(message: types.Message, state: FSMContext):
    if message["from"]["id"] in admin_ids + second_ids:
        await state.finish()
        await message.answer('<b>📊Stats Menu</b>', reply_markup=stats_menu_keyboard)


@dp.callback_query_handler(lambda c: c.data == 'stats_menu', state='*')
async def stats_menu(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.edit_text('<b>📊Stats Menu</b>', reply_markup=stats_menu_keyboard)
