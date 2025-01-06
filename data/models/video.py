from sqlalchemy import Column, Integer, String, BigInteger, Boolean, ForeignKey, PrimaryKeyConstraint

from data.database import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(BigInteger, ForeignKey("users.id"))
    time = Column(Integer)
    video = Column(String)
    is_images = Column(Integer, default=0)
    # Using composite primary key of id and video since a user can have multiple videos
    __table_args__ = (
        PrimaryKeyConstraint("id", "video"),
    )