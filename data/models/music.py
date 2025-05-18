from sqlalchemy import Column, BigInteger, ForeignKey

from data.database import Base


class Music(Base):
    __tablename__ = "music"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    downloaded_at = Column(BigInteger, nullable=True)
    video_id = Column(BigInteger, nullable=False)
