from sqlalchemy import Column, Text, JSON, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base
from datetime import datetime
from sqlalchemy import text



Base = declarative_base()

class StrategyEvent(Base):
    __tablename__ = "strategy_event"
    __table_args__ = (
        UniqueConstraint('event_type', 'order_id', 'trade_id', name='uq_strategy_event_event_order_trade'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    instance_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(Text, nullable=False)        # 'FILL' и т.п.
    order_id = Column(Text, nullable=False)
    trade_id = Column(Text, nullable=True)           # WS trade UUID (event.id), если применимо
    payload = Column(JSONB, nullable=False)
    raw_event = Column(JSONB, nullable=True)         # RAW WS payload для отладки
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    handled_at = Column(DateTime(timezone=True), nullable=True)
