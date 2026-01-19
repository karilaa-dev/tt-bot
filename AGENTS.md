# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Codebase Overview

**tt-bot** is a Telegram bot for downloading TikTok videos, slideshows, and audio without watermarks. Production-grade with proxy rotation, queue management, 3-part retry strategy, and multilingual support.

**Stack:** Python 3.13, aiogram 3.24, yt-dlp, curl_cffi, SQLAlchemy 2.0, asyncpg

**Structure:**
- `main.py` - Main bot entry point
- `tiktok_api/` - TikTok extraction (client.py is the core with 3-part retry)
- `handlers/` - Telegram message handlers
- `data/` - Configuration, database, localization
- `misc/` - Queue management, media processing utilities
- `stats/` - Statistics bot and graphs

For detailed architecture, see [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Common Commands

```bash
# Run the main bot
uv run main.py

# Run the stats bot
uv run stats.py

# Run with Docker
docker-compose up -d

# Install dependencies
uv sync
```

## Key Design Patterns

- **3-part retry strategy**: URL resolution → Video info → Download, each with independent proxy rotation
- **Chrome 120 impersonation**: Fixed browser fingerprint to bypass TikTok WAF blocking
- **Singleton resources**: Shared ThreadPoolExecutor (500), curl session pool (1000/proxy), aiohttp connector
- **Context managers**: VideoInfo implements RAII for yt-dlp resource cleanup
- **Repository pattern**: db_service.py abstracts database operations
- **Queue management**: Per-user concurrency limits via QueueManager

## Critical Gotchas

1. **VideoInfo cleanup**: Slideshows MUST call `.close()` or use `with` statement to release yt-dlp resources
2. **Chrome 120 only**: Newer versions (136+) blocked with proxies due to fingerprint mismatch
3. **Database initialization**: Call `initialize_database_components()` before any DB operations
4. **yt-dlp private API**: Uses `_extract_web_data_and_status()` which may break on yt-dlp updates
5. **ProxySession sticky**: Same proxy used across all 3 parts unless retry triggers rotation

## Adding New Features

- **New command**: Add handler in `handlers/`, register router in `main.py`
- **New language**: Create `data/locale/XX.json` (auto-detected)
- **New TikTok error type**: Add to `tiktok_api/exceptions.py`, handle in `misc/video_types.py:get_error_message()`
- **New unsupported content handler**: Add to `handlers/get_video.py`
