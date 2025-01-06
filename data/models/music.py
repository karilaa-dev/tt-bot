from sqlalchemy import Column, Integer, String, BigInteger, PrimaryKeyConstraint

from data.database import Base


class Music(Base):
    __tablename__ = "music"

    id = Column(BigInteger)
    time = Column(Integer)
    video = Column(String)
    # Using composite primary key of id and music since a user can have multiple music entries
    __table_args__ = (
        PrimaryKeyConstraint("id", "video"),
    )