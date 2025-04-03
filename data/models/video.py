from sqlalchemy import Column, Integer, String, BigInteger, Boolean, ForeignKey, PrimaryKeyConstraint

from data.database import Base


class Video(Base):
    __tablename__ = "videos"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True)
    id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    downloaded_at = Column(BigInteger)
    video = Column(String)
    is_images = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("pk_id"),
    )