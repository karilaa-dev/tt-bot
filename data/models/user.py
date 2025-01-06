from sqlalchemy import Column, Integer, String, BigInteger, Boolean

from data.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    time = Column(Integer)
    lang = Column(String)
    link = Column(String, nullable=True)
    file_mode = Column(Integer, default=0)