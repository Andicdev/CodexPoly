from __future__ import annotations
from sqlalchemy import Column, String, Boolean, TIMESTAMP, Numeric, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from common.base import Base

class GammaMarket(Base):
    __tablename__ = "gamma_market"

    market_id      = Column(String, primary_key=True)  # из Gamma
    event_id       = Column(String, ForeignKey("gamma_event.event_id", ondelete="CASCADE"), nullable=False)

    question       = Column(String, nullable=False)
    outcome_type   = Column(String, nullable=True)     # binary/...
    clob_condition = Column(String, nullable=True)     # conditionId для CLOB торговли
    yes_asset_id   = Column(String, nullable=True)     # CLOB token id для YES
    no_asset_id    = Column(String, nullable=True)     # CLOB token id для NO

    fee_bps        = Column(Integer, nullable=True)

    liquidity_usd  = Column(Numeric(18, 2), nullable=True)  # если будем считать сами — оставим nullable
    end_date_utc   = Column(TIMESTAMP(timezone=True), nullable=True)
    # новое: старт рынка (из eventStartTime) и длительность (end-start) в секундах
    start_date_utc = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_sec   = Column(Integer, nullable=True)
    # новое: оставшееся время до конца рынка (end_date_utc - now), в секундах
    # если end_date_utc отсутствует — NULL
    duration_from_now_sec = Column(Integer, nullable=True)    

    closed         = Column(Boolean, nullable=False, server_default=text("false"))
    resolved       = Column(Boolean, nullable=False, server_default=text("false"))
    updated_at_utc = Column(TIMESTAMP(timezone=True), nullable=False)
    # когда последний раз видели рынок активным (closed=false AND resolved=false)
    last_seen_active_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # ---- UMA / Resolution status (нормализованные поля) ----
    # pending / proposed / disputed / resolved / ...
    uma_resolution_status = Column(String, nullable=True)
    # время UMA (если приходит от Gamma как umaEndDate)
    uma_end_date_utc      = Column(TIMESTAMP(timezone=True), nullable=True)
    # когда uma_resolution_status поменялся последний раз (для алертов)
    uma_status_changed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # ---- Дополнительные поля из Gamma API ----
    new               = Column(Boolean, nullable=False, server_default=text("false"))
    spread            = Column(Numeric(18, 6), nullable=True)
    bestAsk           = Column(Numeric(18, 6), nullable=True)
    bestBid           = Column(Numeric(18, 6), nullable=True)
    volume            = Column(Numeric(24, 6), nullable=True)
    liquidity         = Column(Numeric(24, 6), nullable=True)
    competitive       = Column(Numeric(18, 12), nullable=True)
    volume24hrClob    = Column(Numeric(24, 6), nullable=True)
    acceptingOrders   = Column(Boolean, nullable=False, server_default=text("false"))
    enableOrderBook   = Column(Boolean, nullable=False, server_default=text("false"))

    # минимальный размер ордера и последняя цена трейда (из Gamma API)
    order_min_size    = Column(Numeric(18, 6), nullable=True)
    last_trade_price  = Column(Numeric(18, 6), nullable=True)
    neg_risk          = Column(Boolean, nullable=True)
 
    raw            = Column(JSONB, nullable=False)
    # когда мы впервые записали рынок в gamma_market (ингест)
    added_at       = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at     = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at     = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
