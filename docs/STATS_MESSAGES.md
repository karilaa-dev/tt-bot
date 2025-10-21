# Creating Stats Messages

This project includes a Docker script to create stats and daily message IDs. The script sends two simple messages to a specified chat and outputs their message IDs, which you can then use in your `.env` file.

## Usage

### Option 1: Using the Shell Script (Recommended)

```bash
./scripts/create-stats-messages.sh <chat_id>
```

Example:
```bash
./scripts/create-stats-messages.sh -1001234567890
```

### Option 2: Using Docker Compose Directly

```bash
docker compose --profile tools run --rm create-stats-messages python create_stats_messages.py <chat_id>
```

Example:
```bash
docker compose --profile tools run --rm create-stats-messages python create_stats_messages.py -1001234567890
```

### Option 3: Running Locally

```bash
python create_stats_messages.py <chat_id>
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

- Docker and Docker Compose installed
- `.env` file configured with bot token
- Bot must be an administrator in the target chat (if it's a group)