from configparser import ConfigParser
from json import loads as json_loads

config = ConfigParser()
config.read("config.ini")
admin_ids = json_loads(config["bot"]["admin_ids"])
second_ids = admin_ids + json_loads(config["bot"]["second_ids"])
api_alt_mode = config["api"].getboolean("alt_mode")

with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json_loads(locale_file.read())
