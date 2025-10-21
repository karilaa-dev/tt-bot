#!/usr/bin/env python3
"""
Script to create stats and daily message IDs.
Sends two messages to the specified chat and outputs their message IDs.
"""
import asyncio
import sys
import os
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.config import config
from stats.loader import bot


async def create_stats_messages(chat_id: int):
    """Create stats and daily messages and return their IDs."""
    
    try:
        # Send overall stats message
        overall_message = await bot.send_message(
            chat_id=chat_id,
            text="STATS_MESSAGE_ID"
        )
        overall_message_id = overall_message.message_id
        
        # Send daily stats message
        daily_message = await bot.send_message(
            chat_id=chat_id,
            text="DAILY_STATS_MESSAGE_ID"
        )
        daily_message_id = daily_message.message_id
        
        return overall_message_id, daily_message_id
        
    except Exception as e:
        logging.error(f"Error creating stats messages: {e}")
        raise


async def main():
    """Main function to run the script."""
    if len(sys.argv) != 2:
        print("Usage: python create_stats_messages.py <chat_id>")
        print("Example: python create_stats_messages.py -1001234567890")
        sys.exit(1)
    
    try:
        chat_id = int(sys.argv[1])
    except ValueError:
        print("Error: chat_id must be an integer")
        sys.exit(1)
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    try:
        overall_id, daily_id = await create_stats_messages(chat_id)
        
        print(f"Successfully created stats messages in chat {chat_id}:")
        print(f"Overall stats message ID: {overall_id}")
        print(f"Daily stats message ID: {daily_id}")
        print(f"\nAdd these to your .env file:")
        print(f"STATS_MESSAGE_ID={overall_id}")
        print(f"DAILY_STATS_MESSAGE_ID={daily_id}")
        
    except Exception as e:
        logging.error(f"Failed to create stats messages: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())