from __future__ import annotations
from sqlalchemy import Column, String, TIMESTAMP, Enum, JSON, text
from enum import Enum as PyEnum
from common.base import Base


class StrategyStatus(PyEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class Strategy(Base):
    __tablename__ = "strategy"

    id         = Column(String, primary_key=True)  # UUID строкой
    name       = Column(String, nullable=False)
    kind       = Column(String, nullable=False)    # e.g. 'MARKET_MAKER', 'TREND_EXECUTOR'
    status     = Column(Enum(StrategyStatus, name="strategy_status"), nullable=False, server_default=text("'ENABLED'"))
    params     = Column(JSON, nullable=True)       # произвольные входные параметры
    tg_chat_id = Column(String, nullable=True)     # ← КАНАЛ по умолчанию для всех уведомлений стратегии
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
