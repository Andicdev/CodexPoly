from sqlalchemy import Column, Integer, String, Numeric, TIMESTAMP, ForeignKey
from common.base import Base
from datetime import datetime

class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("market_strategies.id"), nullable=False)
    order_type = Column(String, nullable=False)
    side = Column(String, nullable=False)
    size = Column(Numeric, nullable=False)
    price = Column(Numeric, nullable=False)              # запрошенная цена
    executed_price = Column(Numeric, nullable=True)      # реальная
    order_id = Column(String, nullable=True)
    executed_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    pnl = Column(Numeric, nullable=True)
    comment = Column(String, nullable=True)

