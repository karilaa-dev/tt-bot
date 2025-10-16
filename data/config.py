import os
from json import loads as json_loads

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


config = {
    "bot": {
        "token": os.getenv("BOT_TOKEN", ""),
        "stats_token": os.getenv("STATS_BOT_TOKEN", ""),
        "admin_ids": json_loads(os.getenv("ADMIN_IDS", "[]")),
        "second_ids": json_loads(os.getenv("SECOND_IDS", "[]")),
        "tg_server": os.getenv("TG_SERVER", "https://api.telegram.org"),
        "db_url": os.getenv("DB_URL", ""),
        "db_path": os.getenv("DB_PATH", ""),
        "db_name": os.getenv("DB_NAME", ""),
    },
    "api": {
        "alt_mode": os.getenv("ALT_MODE", "false").lower() == "true",
        "api_link": os.getenv("API_LINK", ""),
        "rapid_token": os.getenv("RAPID_TOKEN", ""),    
        "botstat": os.getenv("BOTSTAT", ""),
    },
    "logs": {
        "join_logs": os.getenv("JOIN_LOGS", "0"),
        "backup_logs": os.getenv("BACKUP_LOGS", "0"),
        "stats_chat": os.getenv("STATS_CHAT", "0"),
        "stats_message_id": os.getenv("STATS_MESSAGE_ID", "0"),
        "daily_stats_message_id": os.getenv("DAILY_STATS_MESSAGE_ID", "0"),
    },
}

admin_ids = config["bot"]["admin_ids"]
second_ids = admin_ids + config["bot"]["second_ids"]
api_alt_mode = config["api"]["alt_mode"]

with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json_loads(locale_file.read())
