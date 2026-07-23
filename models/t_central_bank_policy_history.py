from __future__ import annotations

from sqlalchemy import BigInteger, Index, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from common.base import Base


class CentralBankPolicyHistory(Base):
    __tablename__ = "central_bank_policy_history"

    __table_args__ = (
        UniqueConstraint(
            "bank_code",
            "instrument_code",
            "decision_time_utc",
            name="uq_cb_policy_series",
        ),
        Index(
            "ix_cb_policy_series_time",
            "bank_code",
            "instrument_code",
            "decision_time_utc",
        ),
        Index("ix_cb_policy_ingest_id", "ingest_id"),
        Index("ix_cb_policy_source_doc_type", "source", "source_doc_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    bank_code: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_code: Mapped[str] = mapped_column(Text, nullable=False)

    decision_time_utc: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    effective_time_utc: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    target_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    prev_target_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    change_bps: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    direction: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_doc_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    ingest_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extracted_value_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="now()",
    )
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="now()",
    )