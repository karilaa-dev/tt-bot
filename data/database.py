from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import logging

from data.db_utils import get_async_db_url

# Setup logging for this module (optional, but good practice)
logger = logging.getLogger(__name__)

# Declare engine and async_session at the module level, to be initialized later
engine = None
async_session = None

Base = declarative_base()

def initialize_database_components(db_url: str):
    """
    Initialize database engine and session factory.
    
    Call this function once during application startup before any database operations.
    Must be called before using init_db(), get_db(), or get_session().
    
    Args:
        db_url: Database connection URL string
        
    Side effects:
        - Sets global engine and async_session variables
        - Creates SQLAlchemy async engine with the provided URL
        - Creates session factory for AsyncSession instances
        - Logs the effective database URL being used
        
    Raises:
        RuntimeError: If called multiple times (will overwrite existing globals)
    """
    global engine, async_session

    # Get the processed URL for the engine
    engine_url = get_async_db_url(db_url)

    # The logger in get_async_db_url already logs the original and effective URL.
    # We can add a specific log for this context if needed, e.g.:
    logger.info(f"Using database URL for engine in data/database.py: {str(engine_url)}")

    engine = create_async_engine(engine_url, echo=False)
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def init_db():
    # Ensure engine is initialized before calling this
    if engine is None:
        raise RuntimeError("Database engine not initialized. Call initialize_database_components first.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    # Ensure async_session is initialized
    if async_session is None:
        raise RuntimeError("Database session factory not initialized. Call initialize_database_components first.")
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Context manager for database sessions
async def get_session() -> AsyncSession:
    # Ensure async_session is initialized
    if async_session is None:
        raise RuntimeError("Database session factory not initialized. Call initialize_database_components first.")
    async with async_session() as session:
        return session
