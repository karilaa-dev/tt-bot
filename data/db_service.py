from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import func, desc

from data.database import get_session
from data.models import User, Video, Music


from sqlalchemy import select, update

async def get_user(user_id: int) -> Optional[User]:
    async with await get_session() as db:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def create_user(user_id: int, lang: str, link: Optional[str] = None) -> User:
    async with await get_session() as db:
        user = User(id=user_id, time=int(datetime.now().timestamp()), lang=lang, link=link)
        db.add(user)
        await db.commit()
        return user


async def update_user_mode(user_id: int, file_mode: bool) -> None:
    async with await get_session() as db:
        stmt = update(User).where(User.id == user_id).values(file_mode=1 if file_mode else 0)
        await db.execute(stmt)
        await db.commit()


async def get_user_stats(user_id: int) -> Tuple[Optional[User], int, int]:
    async with await get_session() as db:
        # Get user
        stmt = select(User).where(User.id == user_id)
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
        stmt = select(Video.time, Video.video).where(Video.id == user_id)
        result = await db.execute(stmt)
        return result.all()


async def get_referral_stats() -> List[Tuple[str, int]]:
    async with await get_session() as db:
        stmt = (
            select(User.link, func.count(User.link).label('cnt'))
            .where(User.link != None)
            .group_by(User.link)
            .order_by(desc('cnt'))
            .limit(10)
        )
        result = await db.execute(stmt)
        return result.all()


async def get_other_stats() -> Tuple[int, List[Tuple[str, int]], List[Tuple[int, int]]]:
    async with await get_session() as db:
        # Get file mode count
        stmt = select(func.count(User.id)).where(User.file_mode == 1)
        result = await db.execute(stmt)
        file_mode_count = result.scalar()
        
        # Get top languages
        stmt = (
            select(User.lang, func.count(User.lang).label('cnt'))
            .group_by(User.lang)
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
            conditions.append(Video.time >= current_time - period)
            
        if chat_type == 'users':
            conditions.append(Video.id > 0)
        elif chat_type == 'groups':
            conditions.append(Video.id < 0)
            
        stmt = select(Video.time, Video.video)
        if conditions:
            stmt = stmt.where(*conditions)
            
        result = await db.execute(stmt)
        return result.all()


async def get_user_settings(user_id: int) -> Optional[Tuple[str, bool]]:
    async with await get_session() as db:
        stmt = select(User.lang, User.file_mode).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.first()
        if user:
            return user[0], bool(user[1])
        return None


async def add_video(user_id: int, video_link: str, is_images: bool) -> None:
    async with await get_session() as db:
        video = Video(id=user_id, time=int(datetime.now().timestamp()), video=video_link, is_images=1 if is_images else 0)
        db.add(video)
        await db.commit()


async def add_music(user_id: int, video_id: str) -> None:
    async with await get_session() as db:
        music = Music(id=user_id, time=int(datetime.now().timestamp()), video=video_id)
        db.add(music)
        await db.commit()


async def update_user_lang(user_id: int, lang: str) -> None:
    async with await get_session() as db:
        stmt = update(User).where(User.id == user_id).values(lang=lang)
        await db.execute(stmt)
        await db.commit()


async def get_user_ids(only_positive: bool = True) -> List[int]:
    async with await get_session() as db:
        stmt = select(User.id)
        if only_positive:
            stmt = stmt.where(User.id > 0)
        result = await db.execute(stmt)
        return [id[0] for id in result.all()]