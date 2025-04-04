from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey

from data.database import Base


class Video(Base):
    __tablename__ = "videos"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    downloaded_at = Column(BigInteger, nullable=True)
    video = Column(String, nullable=False)
    is_images = Column(Boolean, default=False, nullable=False)
