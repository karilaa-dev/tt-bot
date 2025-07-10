from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey

from data.database import Base


class Video(Base):
    __tablename__ = "videos"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    downloaded_at = Column(BigInteger, nullable=True)
    video_link = Column(String, nullable=False)
    is_images = Column(Boolean, default=False, nullable=False)
    is_processed = Column(Boolean, default=False, nullable=False)
    is_inline = Column(Boolean, default=False, nullable=False)
