from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import func, desc

from data.database import db_session
from data.models import User, Video, Music


def get_user(user_id: int) -> Optional[User]:
    with db_session() as db:
        return db.query(User).filter(User.id == user_id).first()


def create_user(user_id: int, lang: str, link: Optional[str] = None) -> User:
    with db_session() as db:
        user = User(id=user_id, time=int(datetime.now().timestamp()), lang=lang, link=link)
        db.add(user)
        db.commit()
        return user


def update_user_mode(user_id: int, file_mode: bool) -> None:
    with db_session() as db:
        db.query(User).filter(User.id == user_id).update({"file_mode": 1 if file_mode else 0})
        db.commit()


def get_user_stats(user_id: int) -> Tuple[Optional[User], int, int]:
    with db_session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None, 0, 0
        videos_count = db.query(func.count(Video.video)).filter(Video.id == user_id).scalar()
        images_count = db.query(func.count(Video.video)).filter(
            Video.id == user_id, Video.is_images == True).scalar()
        return user, videos_count, images_count


def get_user_videos(user_id: int) -> List[Tuple[int, str]]:
    with db_session() as db:
        return db.query(Video.time, Video.video).filter(Video.id == user_id).all()


def get_referral_stats() -> List[Tuple[str, int]]:
    with db_session() as db:
        return db.query(User.link, func.count(User.link).label('cnt'))\
            .filter(User.link != None)\
            .group_by(User.link)\
            .order_by(desc('cnt'))\
            .limit(10)\
            .all()


def get_other_stats() -> Tuple[int, List[Tuple[str, int]], List[Tuple[int, int]]]:
    with db_session() as db:
        file_mode_count = db.query(func.count(User.id)).filter(User.file_mode == 1).scalar()
        
        
        top_langs = db.query(User.lang, func.count(User.lang).label('cnt'))\
            .group_by(User.lang)\
            .order_by(desc('cnt'))\
            .all()
        
        top_users = db.query(Video.id, func.count(Video.id).label('cnt'))\
            .group_by(Video.id)\
            .order_by(desc('cnt'))\
            .limit(10)\
            .all()
        
        return file_mode_count, top_langs, top_users


def get_stats_by_period(period: int = 0, chat_type: str = 'all') -> List[Tuple[int, str]]:
    with db_session() as db:
        query = db.query(Video.time, Video.video)
        
        if period > 0:
            current_time = int(datetime.now().timestamp())
            query = query.filter(Video.time >= current_time - period)
            
        if chat_type == 'users':
            query = query.filter(Video.id > 0)
        elif chat_type == 'groups':
            query = query.filter(Video.id < 0)
            
        return query.all()


def get_user_settings(user_id: int) -> Optional[Tuple[str, bool]]:
    with db_session() as db:
        user = db.query(User.lang, User.file_mode).filter(User.id == user_id).first()
        if user:
            return user[0], bool(user[1])
        return None


def add_video(user_id: int, video_link: str, is_images: bool) -> None:
    with db_session() as db:
        video = Video(id=user_id, time=int(datetime.now().timestamp()), video=video_link, is_images=1 if is_images else 0)
        db.add(video)
        db.commit()


def add_music(user_id: int, video_id: str) -> None:
    with db_session() as db:
        music = Music(id=user_id, time=int(datetime.now().timestamp()), video=video_id)
        db.add(music)
        db.commit()


def update_user_lang(user_id: int, lang: str) -> None:
    with db_session() as db:
        db.query(User).filter(User.id == user_id).update({"lang": lang})
        db.commit()


def get_user_ids(only_positive: bool = True) -> List[int]:
    with db_session() as db:
        query = db.query(User.id)
        if only_positive:
            query = query.filter(User.id > 0)
        return [id[0] for id in query.all()]