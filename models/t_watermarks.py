# models/t_watermarks.py
from sqlalchemy import Column, Text, TIMESTAMP, BigInteger
from common.base import Base

class Watermark(Base):
    __tablename__ = "watermarks"

    name = Column(Text, primary_key=True)
    ts = Column(TIMESTAMP(timezone=True), nullable=False)          # значение watermark (timestamptz)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)  # когда обновили
    last_block = Column(BigInteger, nullable=True)               # опционально: последний обработанный блок (для RPC)
