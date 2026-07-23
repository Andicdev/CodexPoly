from sqlalchemy import BigInteger, Integer, Text, DateTime, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base  # как у тебя называется declarative base

class MonitoredNews(Base):
    __tablename__ = "monitored_news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    tg_chat_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    condition_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_qty: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    order_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    last_run_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)