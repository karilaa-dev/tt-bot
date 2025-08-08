from sqlalchemy import Column, String, BigInteger, Boolean

from data.database import Base


class Users(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
    registered_at = Column(BigInteger, nullable=True)
    lang = Column(String, default='en', nullable=False)
    link = Column(String, nullable=True)
    file_mode = Column(Boolean, default=False, nullable=False)
