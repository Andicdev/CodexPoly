from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.db import Base

class ExtractedValue(Base):
    __tablename__ = "extracted_values"

    id = Column(BigInteger, primary_key=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    ingest_id = Column(BigInteger, ForeignKey("ingested_docs.id", ondelete="SET NULL"), nullable=True)

    ticker = Column(Text, nullable=False)
    metric_key = Column(Text, nullable=False)

    value_num = Column(Numeric, nullable=True)
    value_raw = Column(Text, nullable=True)

    period_end = Column(Date, nullable=True)
    period_type = Column(Text, nullable=True)
    quarter = Column(Text, nullable=True)

    confidence = Column(Numeric, nullable=True)
    evidence = Column(JSONB, nullable=False, server_default="{}")

    resolver_name = Column(Text, nullable=True)
    resolver_ver = Column(Text, nullable=True)

    trade_status = Column(Text, nullable=False, server_default="NEW")
    trade_error = Column(Text, nullable=True)
    trade_updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    company = relationship("Company", backref="extracted_values")
    ingest = relationship("IngestedDoc", backref="extracted_values")