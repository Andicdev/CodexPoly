from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


class Outcome(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(str, Enum):
    GTC = "GTC"


@dataclass(frozen=True)
class KeepOpenPolicy:
    """Leave a successfully submitted GTC order unchanged."""

    kind: str = field(default="keep_open", init=False)


@dataclass(frozen=True)
class RepriceOnTickChange:
    """Cancel and replace only this order group when a finer tick becomes valid."""

    old_tick: Decimal
    new_tick: Decimal
    max_reprices: int = 1
    submit_first: bool = True
    kind: str = field(default="reprice_on_tick_change", init=False)
    cancel_scope: str = field(default="order_group", init=False)

    def __post_init__(self) -> None:
        old_tick = Decimal(str(self.old_tick))
        new_tick = Decimal(str(self.new_tick))
        if old_tick <= 0 or new_tick <= 0:
            raise ValueError("tick sizes must be positive")
        if new_tick >= old_tick:
            raise ValueError("new_tick must be finer than old_tick")
        if self.max_reprices < 1:
            raise ValueError("max_reprices must be positive")
        if not isinstance(self.submit_first, bool):
            raise TypeError("submit_first must be a bool")
        object.__setattr__(self, "old_tick", old_tick)
        object.__setattr__(self, "new_tick", new_tick)


OrderLifecyclePolicy: TypeAlias = KeepOpenPolicy | RepriceOnTickChange


@dataclass(frozen=True)
class OrderTemplate:
    """Static order candidate that can be prepared before a source resolves."""

    template_id: str
    strategy_id: str
    account_name: str
    condition_id: str
    outcome: Outcome
    side: OrderSide
    desired_price: Decimal
    quantity: Decimal | None = None
    notional: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    lifecycle_policy: OrderLifecyclePolicy = field(default_factory=KeepOpenPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_order_fields(self)

    def bind(self, *, signal_id: str) -> OrderIntent:
        """Create the concrete, idempotent intent selected by a strategy."""

        normalized_signal_id = _required_text(signal_id, "signal_id")
        return OrderIntent(
            intent_id=f"{normalized_signal_id}/{self.template_id}",
            signal_id=normalized_signal_id,
            template_id=self.template_id,
            strategy_id=self.strategy_id,
            account_name=self.account_name,
            condition_id=self.condition_id,
            outcome=self.outcome,
            side=self.side,
            desired_price=self.desired_price,
            quantity=self.quantity,
            notional=self.notional,
            time_in_force=self.time_in_force,
            lifecycle_policy=self.lifecycle_policy,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class OrderIntent:
    """Validated order selected by a strategy for one resolution signal."""

    intent_id: str
    signal_id: str
    template_id: str
    strategy_id: str
    account_name: str
    condition_id: str
    outcome: Outcome
    side: OrderSide
    desired_price: Decimal
    quantity: Decimal | None = None
    notional: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    lifecycle_policy: OrderLifecyclePolicy = field(default_factory=KeepOpenPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _required_text(self.intent_id, "intent_id"))
        object.__setattr__(self, "signal_id", _required_text(self.signal_id, "signal_id"))
        _normalize_order_fields(self)


def _normalize_order_fields(order: OrderTemplate | OrderIntent) -> None:
    for name in (
        "template_id",
        "strategy_id",
        "account_name",
        "condition_id",
    ):
        object.__setattr__(order, name, _required_text(getattr(order, name), name))

    desired_price = Decimal(str(order.desired_price))
    if desired_price <= 0 or desired_price >= 1:
        raise ValueError("desired_price must be greater than 0 and less than 1")
    object.__setattr__(order, "desired_price", desired_price)

    quantity = _optional_positive_decimal(order.quantity, "quantity")
    notional = _optional_positive_decimal(order.notional, "notional")
    if (quantity is None) == (notional is None):
        raise ValueError("exactly one of quantity or notional is required")
    object.__setattr__(order, "quantity", quantity)
    object.__setattr__(order, "notional", notional)

    if not isinstance(order.outcome, Outcome):
        object.__setattr__(order, "outcome", Outcome(str(order.outcome).upper()))
    if not isinstance(order.side, OrderSide):
        object.__setattr__(order, "side", OrderSide(str(order.side).upper()))
    if not isinstance(order.time_in_force, TimeInForce):
        object.__setattr__(
            order,
            "time_in_force",
            TimeInForce(str(order.time_in_force).upper()),
        )
    if not isinstance(order.lifecycle_policy, (KeepOpenPolicy, RepriceOnTickChange)):
        raise TypeError("unsupported lifecycle_policy")

    object.__setattr__(
        order,
        "metadata",
        MappingProxyType(dict(order.metadata)),
    )


def _optional_positive_decimal(
    value: Decimal | None,
    name: str,
) -> Decimal | None:
    if value is None:
        return None
    normalized = Decimal(str(value))
    if normalized <= 0:
        raise ValueError(f"{name} must be positive")
    return normalized


def _required_text(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized
