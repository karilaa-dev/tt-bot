from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import func, desc

from data.database import get_session
from data.models import Users, Video, Music


from sqlalchemy import select, update

async def get_user(user_id: int) -> Optional[Users]:
    async with await get_session() as db:
        stmt = select(Users).where(Users.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def create_user(user_id: int, lang: str, link: Optional[str] = None) -> Users:
    async with await get_session() as db:
        user = Users(id=user_id, time=int(datetime.now().timestamp()), lang=lang, link=link)
        db.add(user)
        await db.commit()
        return user


async def update_user_mode(user_id: int, file_mode: bool) -> None:
    async with await get_session() as db:
        stmt = update(Users).where(Users.id == user_id).values(file_mode=file_mode)
        await db.execute(stmt)
        await db.commit()


async def get_user_stats(user_id: int) -> Tuple[Optional[Users], int, int]:
    async with await get_session() as db:
        # Get user
        stmt = select(Users).where(Users.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None, 0, 0
        
        # Get video count
        stmt = select(func.count(Video.video)).where(Video.id == user_id)
        result = await db.execute(stmt)
        videos_count = result.scalar()
        
        # Get images count
        stmt = select(func.count(Video.video)).where(Video.id == user_id, Video.is_images == True)
        result = await db.execute(stmt)
        images_count = result.scalar()
        
        return user, videos_count, images_count


async def get_user_videos(user_id: int) -> List[Tuple[int, str]]:
    async with await get_session() as db:
        stmt = select(Video.downloaded_at, Video.video).where(Video.id == user_id)
        result = await db.execute(stmt)
        return result.all()


async def get_referral_stats() -> List[Tuple[str, int]]:
    async with await get_session() as db:
        stmt = (
            select(Users.link, func.count(Users.link).label('cnt'))
            .where(Users.link != None)
            .group_by(Users.link)
            .order_by(desc('cnt'))
            .limit(10)
        )
        result = await db.execute(stmt)
        return result.all()


async def get_other_stats() -> Tuple[int, List[Tuple[str, int]], List[Tuple[int, int]]]:
    async with await get_session() as db:
        # Get file mode count
        stmt = select(func.count(Users.id)).where(Users.file_mode is True)
        result = await db.execute(stmt)
        file_mode_count = result.scalar()
        
        # Get top languages
        stmt = (
            select(Users.lang, func.count(Users.lang).label('cnt'))
            .group_by(Users.lang)
            .order_by(desc('cnt'))
        )
        result = await db.execute(stmt)
        top_langs = result.all()
        
        # Get top users
        stmt = (
            select(Video.id, func.count(Video.id).label('cnt'))
            .group_by(Video.id)
            .order_by(desc('cnt'))
            .limit(10)
        )
        result = await db.execute(stmt)
        top_users = result.all()
        
        return file_mode_count, top_langs, top_users


async def get_stats_by_period(period: int = 0, chat_type: str = 'all') -> List[Tuple[int, str]]:
    async with await get_session() as db:
        conditions = []
        
        if period > 0:
            current_time = int(datetime.now().timestamp())
            conditions.append(Video.downloaded_at >= current_time - period)
            
        if chat_type == 'users':
            conditions.append(Video.id > 0)
        elif chat_type == 'groups':
            conditions.append(Video.id < 0)
            
        stmt = select(Video.downloaded_at, Video.video)
        if conditions:
            stmt = stmt.where(*conditions)
            
        result = await db.execute(stmt)
        return result.all()


async def get_user_settings(user_id: int) -> Optional[Tuple[str, bool]]:
    async with await get_session() as db:
        stmt = select(Users.lang, Users.file_mode).where(Users.id == user_id)
        result = await db.execute(stmt)
        user = result.first()
        if user:
            return user[0], bool(user[1])
        return None


async def add_video(user_id: int, video_link: str, is_images: bool) -> None:
    async with await get_session() as db:
        video = Video(id=user_id, time=int(datetime.now().timestamp()), video=video_link, is_images=is_images)
        db.add(video)
        await db.commit()


async def add_music(user_id: int, video_id: str) -> None:
    async with await get_session() as db:
        music = Music(id=user_id, time=int(datetime.now().timestamp()), video=video_id)
        db.add(music)
        await db.commit()


async def update_user_lang(user_id: int, lang: str) -> None:
    async with await get_session() as db:
        stmt = update(Users).where(Users.id == user_id).values(lang=lang)
        await db.execute(stmt)
        await db.commit()


async def get_user_ids(only_positive: bool = True) -> List[int]:
    async with await get_session() as db:
        stmt = select(Users.id)
        if only_positive:
            stmt = stmt.where(Users.id > 0)
        result = await db.execute(stmt)
        return [id[0] for id in result.all()]