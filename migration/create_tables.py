#!/usr/bin/env python3
"""
Script to create database tables for the TT-Bot application.
This script can be run independently to set up the database schema.
"""

import asyncio
import logging
import os
import sys

# Add the project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy.ext.asyncio import create_async_engine
# Removed: from sqlalchemy import make_url

# Import the Base and models to ensure they're registered
from data.database import Base
from data import models  # Ensure all models are imported via data.models.__init__
from data.db_utils import get_async_db_url  # Added import
from data.config import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5.5s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
async def create_tables():
    """Create all database tables defined in the models."""
    database_url_from_config = config['bot']['db_url']

    # Get the processed URL for the engine
    engine_url = get_async_db_url(database_url_from_config)
    
    # The logger in get_async_db_url already logs the original and effective URL.
    # We can add a specific log for this context if needed, e.g.:
    logger.info(f"Using database URL for engine in create_tables: {str(engine_url)}")

    engine = create_async_engine(engine_url, echo=True)

    logger.info("Creating tables...")
    async with engine.begin() as conn:
        # This will create all tables that inherit from Base
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Tables created successfully!")

    # Close the engine
    await engine.dispose()


async def main():
    """Main function to run the script."""
    logger.info("Starting database tables creation...")
    try:
        await create_tables()
        logger.info("Database setup completed successfully.")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main()) 