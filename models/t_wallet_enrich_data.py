# b/models/t_wallet_enrich_data.py

from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric
from common.db import Base


class WalletEnrichData(Base):
    __tablename__ = "wallet_enrich_data"

    id = Column(Integer, primary_key=True)

    wallet = Column(String(42), nullable=False, unique=True, index=True)


    name = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    profile_image = Column(Text, nullable=True)



    # Data API /activity
    first_activity_ts = Column(DateTime(timezone=True), nullable=True)
    last_activity_ts = Column(DateTime(timezone=True), nullable=True)

    # Data API /traded
    markets_traded_count = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    positions_total_value_usdc = Column(Numeric(24, 6), nullable=True)
