from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from cbr_trading.domain.intents import OrderIntent, Outcome


class ExecutionStatus(str, Enum):
    SKIPPED = "SKIPPED"
    DRY_RUN = "DRY_RUN"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PlacedOrder:
    order_id: str
    asset_id: str
    effective_price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        order_id = self.order_id.strip()
        asset_id = self.asset_id.strip()
        if not order_id:
            raise ValueError("order_id is required")
        if not asset_id:
            raise ValueError("asset_id is required")

        effective_price = Decimal(str(self.effective_price))
        quantity = Decimal(str(self.quantity))
        if effective_price <= 0 or effective_price >= 1:
            raise ValueError("effective_price must be greater than 0 and less than 1")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(self, "effective_price", effective_price)
        object.__setattr__(self, "quantity", quantity)


@dataclass(frozen=True)
class ExecutionHandle:
    """Ownership boundary used by the order supervisor for cancel/replace."""

    order_group_id: str
    intent_id: str
    account_name: str
    condition_id: str
    outcome: Outcome
    asset_id: str
    live_order_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "order_group_id",
            "intent_id",
            "account_name",
            "condition_id",
            "asset_id",
        ):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, normalized)

        if not isinstance(self.outcome, Outcome):
            object.__setattr__(self, "outcome", Outcome(str(self.outcome).upper()))

        order_ids = tuple(str(value).strip() for value in self.live_order_ids)
        if not order_ids or any(not value for value in order_ids):
            raise ValueError("live_order_ids must contain at least one order id")
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("live_order_ids must be unique")
        object.__setattr__(self, "live_order_ids", order_ids)


@dataclass(frozen=True)
class OrderExecutionResult:
    intent: OrderIntent
    status: ExecutionStatus
    attempted: bool
    orders: tuple[PlacedOrder, ...] = ()
    handle: ExecutionHandle | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExecutionStatus):
            object.__setattr__(self, "status", ExecutionStatus(str(self.status).upper()))
        object.__setattr__(self, "orders", tuple(self.orders))

        if self.handle is not None and self.handle.intent_id != self.intent.intent_id:
            raise ValueError("execution handle must belong to the result intent")
        if self.handle is not None:
            if (
                self.handle.account_name != self.intent.account_name
                or self.handle.condition_id != self.intent.condition_id
                or self.handle.outcome != self.intent.outcome
            ):
                raise ValueError("execution handle market ownership does not match intent")
            order_ids = {order.order_id for order in self.orders}
            if not set(self.handle.live_order_ids).issubset(order_ids):
                raise ValueError("execution handle references orders absent from result")
            if any(order.asset_id != self.handle.asset_id for order in self.orders):
                raise ValueError("execution result contains orders for another asset")
        if self.status in {ExecutionStatus.SUBMITTED, ExecutionStatus.PARTIAL}:
            if not self.attempted or not self.orders or self.handle is None:
                raise ValueError(
                    "submitted or partial result requires an attempt, orders, and handle"
                )
        if self.status == ExecutionStatus.DRY_RUN and self.attempted:
            raise ValueError("dry-run result must not be attempted")
        if self.status in {
            ExecutionStatus.REJECTED,
            ExecutionStatus.AMBIGUOUS,
        } and not self.attempted:
            raise ValueError(
                "rejected or ambiguous result requires an execution attempt"
            )

        normalized_error = str(self.error or "").strip() or None
        object.__setattr__(self, "error", normalized_error)
