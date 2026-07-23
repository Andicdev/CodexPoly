from sqlalchemy import Column, Integer, String, Boolean, Numeric, TIMESTAMP
from common.base import Base

class InterestingMarket(Base):
    __tablename__ = "interesting_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(String, nullable=False)
    condition_id = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    end_date = Column(TIMESTAMP, nullable=True)
    start_date = Column(TIMESTAMP, nullable=True)
    description = Column(String, nullable=True)
    active = Column(Boolean, nullable=True)
    closed = Column(Boolean, nullable=True)
    enable_order_book = Column(Boolean, nullable=True)
    order_min_size = Column(Numeric, nullable=True)
    accepting_orders = Column(Boolean, nullable=True)
    neg_risk = Column(Boolean, nullable=True)
    last_trade_price = Column(Numeric, nullable=True)
    best_bid = Column(Numeric, nullable=True)
    best_ask = Column(Numeric, nullable=True)
    approved = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, nullable=True)
    strategy_comment = Column(String, nullable=True)