"""Application factory for creating bot instances with shared configuration."""

import asyncio
from typing import List, Optional

from aiogram import Router, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from data.bot_loader import create_bot_components, setup_db
from data.config import config


class BotApplication:
    """Base bot application class with shared functionality."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or config["bot"]["token"]
        self.bot, self.dp, self.scheduler = create_bot_components(self.token)
        self._routers: List[Router] = []
    
    def include_router(self, router: Router):
        """Add a router to the dispatcher."""
        self._routers.append(router)
    
    def include_routers(self, *routers: Router):
        """Add multiple routers to the dispatcher."""
        self._routers.extend(routers)
    
    async def setup(self):
        """Setup database and include routers."""
        await setup_db(config['bot']['db_url'])
        
        if self._routers:
            self.dp.include_routers(*self._routers)
    
    async def start(self):
        """Start the bot application."""
        await self.setup()
        self.scheduler.start()
        
        bot_info = await self.bot.get_me()
        print(f'{bot_info.full_name} [@{bot_info.username}, id:{bot_info.id}]')
        
        await self.dp.start_polling(self.bot)


class MainBotApplication(BotApplication):
    """Main bot application with all standard routers."""
    
    def __init__(self):
        super().__init__()
        self._setup_routers()
    
    def _setup_routers(self):
        """Setup all standard routers for the main bot."""
        from handlers.admin import admin_router
        from handlers.advert import advert_router
        from handlers.get_music import music_router
        from handlers.get_video import video_router
        from handlers.lang import lang_router
        from handlers.user import user_router
        from handlers.get_inline import inline_router
        
        self.include_routers(
            user_router,
            lang_router,
            admin_router,
            advert_router,
            video_router,
            music_router,
            inline_router
        )


class StatsBotApplication(BotApplication):
    """Stats bot application with stats-specific functionality."""
    
    def __init__(self):
        super().__init__(config["bot"]["stats_token"])
        self._setup_routers()
        self._setup_scheduled_jobs()
    
    def _setup_routers(self):
        """Setup stats router."""
        from stats.router import stats_router
        self.include_router(stats_router)
    
    def _setup_scheduled_jobs(self):
        """Setup scheduled stats jobs if enabled."""
        if config["logs"]["stats_chat"] != "0":
            from stats.misc import update_overall_stats, update_daily_stats
            
            # Split message mode - run both immediately
            self.scheduler.add_job(update_overall_stats, misfire_grace_time=None)
            self.scheduler.add_job(update_daily_stats, misfire_grace_time=None)
            
            # Schedule separate updates
            self.scheduler.add_job(
                update_overall_stats, 
                "interval", 
                hours=1, 
                id='stats_overall', 
                misfire_grace_time=None
            )
            self.scheduler.add_job(
                update_daily_stats, 
                "interval", 
                minutes=5, 
                id='stats_daily', 
                misfire_grace_time=None
            )


def create_main_app() -> MainBotApplication:
    """Factory function to create main bot application."""
    return MainBotApplication()


def create_stats_app() -> StatsBotApplication:
    """Factory function to create stats bot application."""
    return StatsBotApplication()


async def run_main_bot():
    """Run the main bot."""
    app = create_main_app()
    await app.start()


async def run_stats_bot():
    """Run the stats bot."""
    app = create_stats_app()
    await app.start()