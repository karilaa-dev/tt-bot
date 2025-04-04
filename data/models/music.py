from sqlalchemy import Column, BigInteger, ForeignKey

from data.database import Base


class Music(Base):
    __tablename__ = "music"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    downloaded_at = Column(BigInteger, nullable=True)
    video = Column(BigInteger, nullable=False)
