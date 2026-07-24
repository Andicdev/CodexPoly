# FILE: models/t_strategy_instance.py
from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, String, Enum as SAEnum, TIMESTAMP, text, Numeric
from sqlalchemy.dialects.postgresql import JSONB

from common.db import Base


class StrategyInstanceStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    DONE = "DONE"
    COMPLETED = "COMPLETED"


class StrategyInstance(Base):
    __tablename__ = "strategy_instance"

    # В БД это TEXT → держим в модели как String
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Человеческое имя инстанса для управления из Telegram-бота
    # ФАЗА 2: name NOT NULL + UNIQUE (в БД уже включено)
    name = Column(String, nullable=False, unique=True)

    strategy_id = Column(String, nullable=False)  # FK → t_strategy.id (UUID строкой)
    strategy_name = Column(String, nullable=True)  # дублируем name стратегии для удобства в UI/SQL

    # Краткий текст вопроса рынка (копируем из interesting_markets.question)
    question = Column(String, nullable=True)

    condition_id = Column(String, nullable=False)

    # ВАЖНО: name='strategy_instance_status' чтобы привязаться к существующему серверному enum типу
    status = Column(
        SAEnum(
            StrategyInstanceStatus,
            name="strategy_instance_status",
        ),
        nullable=False,
        default=StrategyInstanceStatus.PENDING,
    )

    params = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    runtime_state = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # NEW: отдельное поле под таймеры on_timer — только SkyBuyer туда пишет/читает
    timer_state = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    stats = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    # Итоговые агрегаты для SkyBuyer (или других стратегий при желании):
    #   final_position = YES_filled - NO_filled (нетто-позиция в токенах)
    #   final_pnl      = locked arbitrage PnL по matched pair части (см. SkyBuyer.on_user_trade)
    final_position = Column(Numeric(18, 8), nullable=True)
    final_pnl = Column(Numeric(18, 8), nullable=True)

    # Краткое текстовое объяснение причины закрытия инстанса (для UI/отчётов)
    close_reason = Column(String, nullable=True)
    # Какой trading account использовать для выставления ордеров (TradingAccount.name)
    # Nullable для legacy-инстансов, но для торговых стратегий (buyer) обязателен.
    account_name = Column(String, nullable=True)