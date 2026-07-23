from sqlalchemy import Column, Text, TIMESTAMP, BigInteger, Boolean, Integer, Numeric

from common.base import Base

class AllWallet(Base):
    __tablename__ = "all_wallets"

    wallet = Column(Text, primary_key=True)
    first_seen = Column(TIMESTAMP(timezone=True), nullable=False)
    last_seen  = Column(TIMESTAMP(timezone=True), nullable=False)
    trades_count = Column(BigInteger, nullable=False, default=1)

    # enrichment meta
    enriched_at = Column(TIMESTAMP(timezone=True), nullable=True)
    enrich_status = Column(Text, nullable=True)          # 'queued' | 'ok' | 'partial' | 'error'
    enrich_error  = Column(Text, nullable=True)
    positions_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # aggregates
    open_positions_count   = Column(Integer, nullable=True)
    closed_positions_count = Column(Integer, nullable=True)
    markets_traded_count   = Column(Integer, nullable=True)
    portfolio_value_usdc   = Column(Numeric(38, 6), nullable=True)

    # activity bounds
    first_trade_ts = Column(TIMESTAMP(timezone=True), nullable=True)
    last_trade_ts  = Column(TIMESTAMP(timezone=True), nullable=True)
    has_open_positions = Column(Boolean, nullable=True)

    # scheduling
    next_enrich_after = Column(TIMESTAMP(timezone=True), nullable=True)

    # wallet-subgraph meta
    signer            = Column(Text, nullable=True)                 # signer адрес
    wallet_type       = Column(Text, nullable=True)                 # 'proxy' | 'safe'
    usdc_balance_raw  = Column(BigInteger, nullable=True)           # баланс в минимальных единицах (1e-6)
    usdc_balance      = Column(Numeric(38, 6), nullable=True)       # баланс в USDC с нормальными десятичными
    wallet_created_ts = Column(TIMESTAMP(timezone=True), nullable=True)  # createdAt из сабграфа
    last_transfer_ts  = Column(TIMESTAMP(timezone=True), nullable=True)  # lastTransfer из сабграфа