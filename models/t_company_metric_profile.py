from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.db import Base

class CompanyMetricProfile(Base):
    __tablename__ = "company_metric_profile"

    id = Column(BigInteger, primary_key=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    metric_key = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    source_priority = Column(JSONB, nullable=False, server_default="[]")
    doc_types = Column(JSONB, nullable=False, server_default="[]")

    matchers = Column(JSONB, nullable=False, server_default="{}")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    company = relationship("Company", backref="metric_profiles")