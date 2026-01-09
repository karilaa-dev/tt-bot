# Fix All High & Medium Priority Issues in tt-bot

## Quick Summary
Fix 21 bare except clauses and improve error handling in this TikTok downloader Telegram bot.

## Critical Issues to Fix

### 1. Bare Except Clauses (21 total - HIGH PRIORITY)

**handlers/get_music.py** - 7 instances:
- Lines 33, 63, 68, 74, 92: Replace `except:` with `except (TelegramBadRequest, TelegramAPIError) as e:`
- Add logging and import: `from aiogram.exceptions import TelegramBadRequest, TelegramAPIError`

**handlers/get_video.py** - 4 instances:
- Lines 66, 76, 100, 158: Same pattern as above

**handlers/get_inline.py** - 2 instances:
- Lines 141, 149: Same pattern
- Remove commented code at lines 109-113, 118-121

**stats/router.py** - 3 instances:
- Lines 184, 253, 276: Replace with `except TelegramBadRequest as e:`

**handlers/lang.py** - 1 instance:
- Line 45: Replace with specific exception handling

**handlers/admin.py** - 1 instance:
- Line 19: Add proper exception types and validation

**handlers/advert.py** - 1 instance:
- Line 73: Replace with specific Telegram exceptions

**misc/video_types.py** - 2 instances:
- Lines 225, 434: Use `aiohttp.ClientError` and Telegram exceptions

**tiktok_api/client.py** - 3 generic Exception catches:
- Lines 99-101, 121-122, 132-134, 321-322: Use specific network/file exceptions

### 2. Improve Error Logging (MEDIUM PRIORITY)

In handlers/get_music.py, get_video.py, get_inline.py:
- Replace generic "Cant write into database" with contextual messages
- Include user_id, chat_id, video_id in logs
- Add `exc_info=True` to error logs

### 3. Add Database Error Handling (MEDIUM PRIORITY)

In data/db_service.py:
- Wrap all functions with try/except SQLAlchemyError
- Add logging for database errors
- Return None or appropriate fallback on error

### 4. Add Configuration Validation (MEDIUM PRIORITY)

In data/config.py at end:
```python
def validate_config(config: Config) -> None:
    if not config["bot"]["token"]:
        raise ValueError("BOT_TOKEN required")
    # Add other validations
validate_config(config)
```

### 5. Add Type Hints (LOW PRIORITY)

Add return types to functions in misc/utils.py and misc/video_types.py

## Implementation Template

For each bare except:
```python
# Before:
try:
    operation()
except:
    pass

# After:
try:
    operation()
except (SpecificException1, SpecificException2) as e:
    logger.debug/warning/error(f"Context: {details}: {e}")
    # Appropriate fallback behavior
```

## Testing Checklist
- [ ] Bot starts: `python main.py`
- [ ] Video download works
- [ ] No bare except clauses remain
- [ ] All imports added correctly

## Files in Priority Order
1. handlers/get_music.py
2. handlers/get_video.py
3. handlers/get_inline.py
4. stats/router.py
5. handlers/lang.py
6. handlers/admin.py
7. handlers/advert.py
8. misc/video_types.py
9. tiktok_api/client.py
10. data/db_service.py
11. data/config.py
12. misc/utils.py