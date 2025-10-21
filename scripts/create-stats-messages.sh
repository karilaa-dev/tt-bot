#!/bin/bash

# Script to create stats and daily message IDs using native Telegram API calls
# Usage: ./scripts/create-stats-messages.sh <chat_id> [bot_token]

set -e

# Check if chat_id is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <chat_id> [bot_token]"
    echo "Example: $0 -1001234567890 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    echo "If bot_token is not provided, will use STATS_BOT_TOKEN from .env file"
    exit 1
fi

CHAT_ID=$1
BOT_TOKEN=${2:-$(grep STATS_BOT_TOKEN .env 2>/dev/null | cut -d'=' -f2)}

if [ -z "$BOT_TOKEN" ]; then
    echo "Error: Bot token not provided and STATS_BOT_TOKEN not found in .env file"
    exit 1
fi

echo "Creating stats messages in chat: $CHAT_ID"
echo "This will send two messages to the chat and output their message IDs."
echo ""

# Function to send message and get message ID
send_message() {
    local text="$1"
    local response=$(curl -s -X POST \
        "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": $CHAT_ID, \"text\": \"$text\"}")
    
    # Extract message ID from response
    echo "$response" | grep -o '"message_id":[0-9]*' | cut -d':' -f2
}

# Send overall stats message
echo "Sending overall stats message..."
OVERALL_ID=$(send_message "STATS_MESSAGE_ID")

# Send daily stats message  
echo "Sending daily stats message..."
DAILY_ID=$(send_message "DAILY_STATS_MESSAGE_ID")

if [ -n "$OVERALL_ID" ] && [ -n "$DAILY_ID" ]; then
    echo ""
    echo "Successfully created stats messages in chat $CHAT_ID:"
    echo "Overall stats message ID: $OVERALL_ID"
    echo "Daily stats message ID: $DAILY_ID"
    echo ""
    echo "Add these to your .env file:"
    echo "STATS_MESSAGE_ID=$OVERALL_ID"
    echo "DAILY_STATS_MESSAGE_ID=$DAILY_ID"
else
    echo "Error: Failed to send messages. Check bot token and permissions."
    exit 1
fi