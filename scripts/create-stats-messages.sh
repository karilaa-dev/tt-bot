#!/bin/bash

# Script to create stats and daily message IDs using Docker
# Usage: ./scripts/create-stats-messages.sh <chat_id>

set -e

# Check if chat_id is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <chat_id>"
    echo "Example: $0 -1001234567890"
    exit 1
fi

CHAT_ID=$1

echo "Creating stats messages in chat: $CHAT_ID"
echo "This will send two messages to the chat and output their message IDs."
echo ""

# Run the script using Docker Compose with the tools profile
docker compose --profile tools run --rm create-stats-messages python create_stats_messages.py "$CHAT_ID"