from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Text, Numeric, func, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base


class NewsTradeConfirmation(Base):
    __tablename__ = "news_trade_confirmations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ev_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ingest_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sub_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)

    account_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_qty: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    order_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tg_chat_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    confirmed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
