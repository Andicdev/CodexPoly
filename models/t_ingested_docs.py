from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from common.db import Base

class IngestedDoc(Base):
    __tablename__ = "ingested_docs"

    id = Column(BigInteger, primary_key=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    ticker = Column(Text, nullable=False)
    cik = Column(Text, nullable=True)

    source = Column(Text, nullable=False)
    doc_type = Column(Text, nullable=False)

    url = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)

    dedup_key = Column(Text, nullable=False, unique=True)
    payload = Column(JSONB, nullable=False, server_default="{}")

    status = Column(Text, nullable=False, server_default="NEW")
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    company = relationship("Company", backref="ingested_docs")