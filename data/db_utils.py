import logging
from sqlalchemy import make_url
from sqlalchemy.engine.url import URL

logger = logging.getLogger(__name__)

def get_async_db_url(db_url_str: str) -> URL:
    """
    Parses a database URL string and ensures it's configured for asyncpg if it's a PostgreSQL URL.

    Args:
        db_url_str: The database URL string from the configuration.

    Returns:
        A SQLAlchemy URL object, potentially modified for asyncpg.
    """
    logger.info(f"Original database URL received: {db_url_str}")
    url_obj = make_url(db_url_str)
    final_url = url_obj

    if url_obj.get_dialect().name == 'postgresql':
        if url_obj.drivername != 'postgresql+asyncpg':
            current_driver = url_obj.drivername
            if current_driver == 'postgresql': # Default or unspecified
                logger.info(
                    f"PostgreSQL URL detected (driver: '{current_driver}'). "
                    f"SQLAlchemy defaults to asyncpg if installed. Making it explicit to 'postgresql+asyncpg'."
                )
            else: # e.g., postgresql+psycopg2 or other
                logger.info(
                    f"PostgreSQL URL detected with driver '{current_driver}'. "
                    f"Modifying to 'postgresql+asyncpg' to ensure asyncpg driver is used."
                )
            final_url = url_obj.set(drivername="postgresql+asyncpg")
            logger.info(f"Effective database URL for engine: {str(final_url)}")
        else:
            logger.info(f"PostgreSQL URL already specifies 'postgresql+asyncpg' driver: {str(url_obj)}")
    else:
        logger.info(
            f"Database URL dialect is '{url_obj.get_dialect().name}', not PostgreSQL. "
            f"Using as is: {str(url_obj)}"
        )
    return final_url 