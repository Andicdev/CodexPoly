from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.base import Base  

class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    wallet_address: Mapped[str] = mapped_column(Text, nullable=False)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    venue: Mapped[str] = mapped_column(Text, nullable=False, server_default="polymarket_clob")

    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_passphrase: Mapped[str | None] = mapped_column(Text, nullable=True)

    api_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enc_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ✅ если true — новый multi-userchannel воркер будет поднимать WS /ws/user для этого аккаунта
    user_channel_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Если задан — отправлять уведомления по этому аккаунту в указанный чат/канал.
    # Если NULL/пусто — используем дефолтное поведение (как раньше).
    telegram_chat_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "Галочка": если true — уведомлять только когда есть полностью исполненный ордер (FILLED/MATCHED full).
    notify_only_filled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    pk_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    signature_type: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(wallet_address) >= 10", name="trading_accounts_wallet_address_chk"),
    )
