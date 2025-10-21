# Creating Stats Messages

This project includes a bash script to create stats and daily message IDs. The script sends two simple messages to a specified chat using Telegram's Bot API and outputs their message IDs, which you can then use in your `.env` file.

## Usage

### Using the Shell Script

```bash
./scripts/create-stats-messages.sh <chat_id> [bot_token]
```

Examples:
```bash
# Uses STATS_BOT_TOKEN from .env file
./scripts/create-stats-messages.sh -1001234567890

# Provide bot token directly
./scripts/create-stats-messages.sh -1001234567890 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

## What It Does

The script will:
1. Send a message with text "STATS_MESSAGE_ID" to the specified chat
2. Send a message with text "DAILY_STATS_MESSAGE_ID" to the specified chat  
3. Output the message IDs for both messages
4. Provide the exact lines to add to your `.env` file

## Output Example

```
Successfully created stats messages in chat -1001234567890:
Overall stats message ID: 123
Daily stats message ID: 124

Add these to your .env file:
STATS_MESSAGE_ID=123
DAILY_STATS_MESSAGE_ID=124
```

## Environment Variables

After running the script, add these variables to your `.env` file:

```env
STATS_MESSAGE_ID=<overall_stats_message_id>
DAILY_STATS_MESSAGE_ID=<daily_stats_message_id>
STATS_CHAT=<chat_id>
```

## Prerequisites

- `curl` command available (usually pre-installed on most systems)
- `.env` file configured with STATS_BOT_TOKEN, or provide bot token as argument
- Bot must be an administrator in the target chat (if it's a group)