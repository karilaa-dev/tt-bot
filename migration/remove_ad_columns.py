import asyncio
from sqlalchemy import inspect, text

from data.database import engine


async def drop_old_columns() -> None:
    async with engine.begin() as conn:
        def get_columns(sync_conn):
            inspector = inspect(sync_conn)
            return [col['name'] for col in inspector.get_columns('users')]

        columns = await conn.run_sync(get_columns)
        if 'latest_ad_shown' in columns:
            await conn.execute(text('ALTER TABLE users DROP COLUMN latest_ad_shown'))
        if 'latest_ad_msgs' in columns:
            await conn.execute(text('ALTER TABLE users DROP COLUMN latest_ad_msgs'))
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(drop_old_columns())
