from data.bot_loader import create_bot_components, setup_db
from data.config import config

# Create stats bot components using the shared loader with stats token
bot, dp, scheduler = create_bot_components(config["bot"]["stats_token"])
