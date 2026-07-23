from sqlalchemy import BigInteger, Boolean, Column, DateTime, Text
from sqlalchemy.sql import func

from common.db import Base  # поправь на свой импорт Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(BigInteger, primary_key=True)
    ticker = Column(Text, nullable=False, unique=True)
    cik = Column(Text, nullable=True)
    name = Column(Text, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())