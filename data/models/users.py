from sqlalchemy import Column, Integer, String, BigInteger, Boolean

from data.database import Base


class Users(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, unique=True)
    registered_at = Column(BigInteger)
    lang = Column(String)
    link = Column(String, nullable=True)
    file_mode = Column(Boolean, default=False)