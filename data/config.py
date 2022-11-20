from configparser import ConfigParser as configparser

from aiogram.bot.api import TelegramAPIServer
from ujson import loads as json_loads

config = configparser()
config.read("config.ini")
admin_ids = json_loads(config["bot"]["admin_ids"])
second_ids = json_loads(config["bot"]["second_ids"])
bot_token = config["bot"]["token"]
logs = config["bot"]["logs"]
upd_chat = config["bot"]["upd_chat"]
upd_id = config["bot"]["upd_id"]
local_server = TelegramAPIServer.from_base(config["bot"]["tg_server"])

with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json_loads(locale_file.read())
