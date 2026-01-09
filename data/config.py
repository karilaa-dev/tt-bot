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
        "stats_ids": json_loads(os.getenv("STATS_IDS", "[]")),
        "tg_server": os.getenv("TG_SERVER", "https://api.telegram.org"),
        "db_url": os.getenv("DB_URL", ""),
        "db_path": os.getenv("DB_PATH", ""),
        "db_name": os.getenv("DB_NAME", ""),
        "storage_channel": os.getenv(
            "STORAGE_CHANNEL_ID", ""
        ),  # Channel for uploading videos to get file_id
    },
    "api": {
        "botstat": os.getenv("BOTSTAT", ""),
        "monetag_url": os.getenv("MONETAG_URL", ""),
    },
    "logs": {
        "join_logs": os.getenv("JOIN_LOGS", "0"),
        "stats_chat": os.getenv("STATS_CHAT", "0"),
        "stats_message_id": os.getenv("STATS_MESSAGE_ID", "0"),
        "daily_stats_message_id": os.getenv("DAILY_STATS_MESSAGE_ID", "0"),
    },
}

admin_ids = config["bot"]["admin_ids"]
second_ids = admin_ids + config["bot"]["second_ids"]
stats_ids = config["bot"]["stats_ids"]
monetag_url = config["api"]["monetag_url"]

locale = {}
locale["langs"] = sorted(
    file.replace(".json", "") for file in os.listdir("locale") if file.endswith(".json")
)
for lang in locale["langs"]:
    with open(f"locale/{lang}.json", "r", encoding="utf-8") as locale_file:
        locale[lang] = json_loads(locale_file.read())
