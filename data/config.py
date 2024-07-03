from configparser import ConfigParser
from json import loads as json_loads

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

config = ConfigParser()
config.read("config.ini")
admin_ids = json_loads(config["bot"]["admin_ids"])
second_ids = json_loads(config["bot"]["second_ids"])
bot_token = config["bot"]["token"]
logs = config["bot"]["logs"]
upd_chat = config["bot"]["upd_chat"]
upd_id = config["bot"]["upd_id"]
local_server = AiohttpSession(api=TelegramAPIServer.from_base(config["bot"]["tg_server"]))
alt_mode = config["api"].getboolean("alt_mode")
api_link = config["api"]["api_link"]
rapid_api = config["api"]["rapid_token"]

with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json_loads(locale_file.read())
