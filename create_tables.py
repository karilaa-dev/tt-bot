#!/usr/bin/env python3
"""
Script to create database tables for the TT-Bot application.
This script can be run independently to set up the database schema.
"""

import asyncio
import logging
from configparser import ConfigParser

from sqlalchemy.ext.asyncio import create_async_engine

# Import the Base and models to ensure they're registered
from data.database import Base
from data import models # Ensure all models are imported via data.models.__init__

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5.5s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from config.ini file."""
    config = ConfigParser()
    config.read("config.ini")
    return config


async def create_tables():
    """Create all database tables defined in the models."""
    config = load_config()
    database_url = config['bot']['db_url']

    logger.info(f"Connecting to database: {database_url}")
    engine = create_async_engine(database_url, echo=True)

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
