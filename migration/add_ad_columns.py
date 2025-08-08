#!/usr/bin/env python3
"""
Migration script to add ad-related columns to the users table.
Adds:
- latest_ad_shown: BigInteger (timestamp of when last ad was shown)
- latest_ad_msgs: BigInteger (count of videos downloaded since last ad, default 0)
"""

import asyncio
import logging
import os
import sys

import asyncpg

# Add the project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from data.config import config

POSTGRES_DSN = config['bot']['db_url']


async def add_ad_columns():
    """Add ad-related columns to the users table."""
    try:
        conn = await asyncpg.connect(POSTGRES_DSN)
        
        # Check if columns already exist
        check_query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'users' 
        AND column_name IN ('latest_ad_shown', 'latest_ad_msgs');
        """
        
        existing_columns = await conn.fetch(check_query)
        existing_column_names = [row['column_name'] for row in existing_columns]
        
        # Add latest_ad_shown column if it doesn't exist
        if 'latest_ad_shown' not in existing_column_names:
            logging.info("Adding latest_ad_shown column...")
            await conn.execute("""
                ALTER TABLE users 
                ADD COLUMN latest_ad_shown BIGINT;
            """)
            logging.info("✓ latest_ad_shown column added successfully")
        else:
            logging.info("latest_ad_shown column already exists, skipping...")
        
        # Add latest_ad_msgs column if it doesn't exist
        if 'latest_ad_msgs' not in existing_column_names:
            logging.info("Adding latest_ad_msgs column...")
            await conn.execute("""
                ALTER TABLE users 
                ADD COLUMN latest_ad_msgs SMALLINT NOT NULL DEFAULT 0;
            """)
            logging.info("✓ latest_ad_msgs column added successfully")
        else:
            logging.info("latest_ad_msgs column already exists, skipping...")
        
        await conn.close()
        logging.info("Migration completed successfully!")
        
    except asyncpg.PostgresError as e:
        logging.error(f"PostgreSQL error during migration: {e}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error during migration: {e}")
        raise


async def main():
    """Main migration function."""
    logging.info("Starting ad columns migration...")
    await add_ad_columns()


if __name__ == "__main__":
    asyncio.run(main()) 