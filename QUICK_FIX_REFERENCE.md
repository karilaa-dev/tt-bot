# Quick Fix Reference Card

## Exception Type Quick Reference

| Operation Type | Exception to Use |
|----------------|------------------|
| Telegram API calls | `TelegramBadRequest, TelegramAPIError` |
| Network requests | `aiohttp.ClientError, asyncio.TimeoutError` |
| Database operations | `SQLAlchemyError` |
| File operations | `OSError, IOError` |
| Value parsing | `ValueError, TypeError, IndexError` |

## Required Imports by File

**handlers/get_music.py, get_video.py, get_inline.py, lang.py, admin.py, advert.py:**
```python
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
import logging
logger = logging.getLogger(__name__)
```

**misc/video_types.py:**
```python
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
import asyncio
```

**data/db_service.py:**
```python
from sqlalchemy.exc import SQLAlchemyError
import logging
logger = logging.getLogger(__name__)
```

## Pattern Replacement Examples

### Pattern 1: Silent Failure (Most Common)
```python
# Before:
try:
    await operation()
except:
    pass

# After:
try:
    await operation()
except (TelegramBadRequest, TelegramAPIError) as e:
    logger.debug(f"Operation failed gracefully: {e}")
```

### Pattern 2: User-Facing Error
```python
# Before:
try:
    await risky_operation()
except:
    await message.reply("Error")

# After:
try:
    await risky_operation()
except (SpecificException1, SpecificException2) as e:
    logger.error(f"Operation failed for user {user_id}: {e}", exc_info=True)
    await message.reply("Error")
```

### Pattern 3: Database Operations
```python
# Before:
async def db_function():
    async with await get_session() as db:
        # database operations

# After:
async def db_function():
    try:
        async with await get_session() as db:
            # database operations
    except SQLAlchemyError as e:
        logger.error(f"Database error in db_function: {e}", exc_info=True)
        return None  # or appropriate fallback
```

## Logging Best Practices

**DEBUG**: Expected failures, non-critical (reactions not supported, message unchanged)
**WARNING**: Recoverable errors that might need attention
**ERROR**: Failures that impact functionality
**Always include**: relevant IDs (user_id, chat_id, video_id) and `exc_info=True` for ERROR level

## Files in Fix Order

1. ✅ handlers/get_music.py (7 fixes)
2. ✅ handlers/get_video.py (4 fixes)
3. ✅ handlers/get_inline.py (2 fixes + code cleanup)
4. ✅ stats/router.py (3 fixes)
5. ✅ handlers/lang.py (1 fix)
6. ✅ handlers/admin.py (1 fix)
7. ✅ handlers/advert.py (1 fix)
8. ✅ misc/video_types.py (2 fixes)
9. ✅ tiktok_api/client.py (improve generic catches)
10. ✅ data/db_service.py (add error handling)
11. ✅ data/config.py (add validation)
12. ✅ misc/utils.py (add type hints)

## Quick Test Commands

```bash
# Syntax check
python -m py_compile handlers/get_music.py

# Import test
python -c "from handlers import get_music"

# Full startup
python main.py
```