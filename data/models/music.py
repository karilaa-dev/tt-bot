from sqlalchemy import Column, Integer, String, BigInteger, PrimaryKeyConstraint, ForeignKey

from data.database import Base


class Music(Base):
    __tablename__ = "music"

    pk_id = Column(BigInteger, primary_key=True, autoincrement=True)
    id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    downloaded_at = Column(BigInteger)
    video = Column(String)

    __table_args__ = (
        PrimaryKeyConstraint("pk_id"),
    )