import os
from json import loads as json_loads

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


config = {
    "bot": {
        "token": os.getenv("BOT_TOKEN", ""),
        "admin_ids": os.getenv("ADMIN_IDS", "[]"),
        "second_ids": os.getenv("SECOND_IDS", "[]"),
        "tg_server": os.getenv("TG_SERVER", "https://api.telegram.org"),
        "db_url": os.getenv("DB_URL", ""),
        "db_path": os.getenv("DB_PATH", ""),
        "db_name": os.getenv("DB_NAME", ""),
    },
    "api": {
        "alt_mode": os.getenv("ALT_MODE", "False"),
        "api_link": os.getenv("API_LINK", ""),
        "rapid_token": os.getenv("RAPID_TOKEN", ""),
        "botstat": os.getenv("BOTSTAT", ""),
    },
    "ads": {
        "adsgrab_block_id": os.getenv("ADSGRAB_BLOCK_ID", ""),
        "video_count_threshold": os.getenv("VIDEO_COUNT_THRESHOLD", "0"),
        "time_threshold_seconds": os.getenv("TIME_THRESHOLD_SECONDS", "0"),
        "registration_ad_suppression_seconds": os.getenv("REGISTRATION_AD_SUPPRESSION_SECONDS", "0"),
    },
    "logs": {
        "join_logs": os.getenv("JOIN_LOGS", "0"),
        "backup_logs": os.getenv("BACKUP_LOGS", "0"),
        "stats_chat": os.getenv("STATS_CHAT", "0"),
        "stats_message_id": os.getenv("STATS_MESSAGE_ID", "0"),
        "daily_stats_message_id": os.getenv("DAILY_STATS_MESSAGE_ID", "0"),
    },
}

admin_ids = json_loads(config["bot"]["admin_ids"])
second_ids = admin_ids + json_loads(config["bot"]["second_ids"])
api_alt_mode = config["api"]["alt_mode"].lower() == "true"

# Ad system configuration
adsgram_block_id = config["ads"]["adsgrab_block_id"]
ad_video_count_threshold = int(config["ads"]["video_count_threshold"])
ad_time_threshold_seconds = int(config["ads"]["time_threshold_seconds"])
registration_ad_suppression_seconds = int(config["ads"]["registration_ad_suppression_seconds"])

with open('locale.json', 'r', encoding='utf-8') as locale_file:
    locale = json_loads(locale_file.read())
