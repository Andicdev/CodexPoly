from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    OrderLifecyclePolicy,
    OrderSide,
    Outcome,
    RepriceOnTickChange,
)
from cbr_trading.domain.results import ExecutionHandle


class OrderGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPRICING = "REPRICING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TrackedOrderStatus(str, Enum):
    LIVE = "LIVE"
    CANCELLED = "CANCELLED"
    REPLACED = "REPLACED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SupervisionEventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    IGNORED = "IGNORED"


@dataclass(frozen=True)
class OrderGroupRegistration:
    order_group_id: str
    intent_id: str
    signal_id: str | None
    template_id: str | None
    strategy_id: str | None
    account_name: str
    condition_id: str
    outcome: Outcome
    asset_id: str
    side: OrderSide | None
    desired_price: Decimal | None
    quantity: Decimal | None
    notional: Decimal | None
    policy_kind: str
    trigger_old_tick: Decimal | None
    trigger_new_tick: Decimal | None
    max_reprices: int
    initial_order_ids: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "order_group_id",
            "intent_id",
            "account_name",
            "condition_id",
            "asset_id",
            "policy_kind",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        for name in ("signal_id", "template_id", "strategy_id"):
            value = str(getattr(self, name) or "").strip() or None
            object.__setattr__(self, name, value)
        if not isinstance(self.outcome, Outcome):
            object.__setattr__(
                self,
                "outcome",
                Outcome(str(self.outcome).upper()),
            )
        if self.side is not None and not isinstance(self.side, OrderSide):
            object.__setattr__(
                self,
                "side",
                OrderSide(str(self.side).upper()),
            )

        for name in (
            "desired_price",
            "quantity",
            "notional",
            "trigger_old_tick",
            "trigger_new_tick",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Decimal(str(value)))
        if self.desired_price is not None and (
            self.desired_price <= 0 or self.desired_price >= 1
        ):
            raise ValueError("desired_price must be between 0 and 1")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.notional is not None and self.notional <= 0:
            raise ValueError("notional must be positive")
        if self.quantity is not None and self.notional is not None:
            raise ValueError("only one sizing mode may be persisted")

        if self.policy_kind == "keep_open":
            if (
                self.trigger_old_tick is not None
                or self.trigger_new_tick is not None
                or self.max_reprices != 0
            ):
                raise ValueError("keep_open cannot define repricing fields")
        elif self.policy_kind == "reprice_on_tick_change":
            if (
                self.trigger_old_tick is None
                or self.trigger_new_tick is None
                or self.trigger_old_tick <= self.trigger_new_tick
                or self.max_reprices < 1
            ):
                raise ValueError("invalid tick-change repricing policy")
            if (
                self.side is None
                or self.desired_price is None
                or (
                    self.quantity is None
                    and self.notional is None
                )
            ):
                raise ValueError(
                    "repricing registration requires side, price, and size"
                )
        else:
            raise ValueError("unsupported order lifecycle policy")

        order_ids = tuple(
            str(order_id or "").strip()
            for order_id in self.initial_order_ids
        )
        if not order_ids or any(not order_id for order_id in order_ids):
            raise ValueError("initial_order_ids must not be empty")
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("initial_order_ids must be unique")
        object.__setattr__(self, "initial_order_ids", order_ids)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True)
class OrderGroupRecord:
    registration: OrderGroupRegistration
    status: OrderGroupStatus
    revision: int
    reprice_count: int
    live_order_ids: tuple[str, ...]
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OrderGroupStatus):
            object.__setattr__(
                self,
                "status",
                OrderGroupStatus(str(self.status).upper()),
            )
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        if self.reprice_count < 0:
            raise ValueError("reprice_count cannot be negative")
        if self.reprice_count > self.registration.max_reprices:
            raise ValueError("reprice_count exceeds max_reprices")
        order_ids = tuple(
            str(order_id or "").strip()
            for order_id in self.live_order_ids
        )
        if any(not order_id for order_id in order_ids):
            raise ValueError("live_order_ids cannot contain empty values")
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("live_order_ids must be unique")
        object.__setattr__(self, "live_order_ids", order_ids)
        object.__setattr__(
            self,
            "last_error",
            str(self.last_error or "").strip() or None,
        )
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                object.__setattr__(
                    self,
                    name,
                    value.astimezone(timezone.utc),
                )


@dataclass(frozen=True)
class SupervisionClaim:
    event_id: str
    order_group_id: str
    acquired: bool
    revision: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "order_group_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        reason = str(self.reason or "").strip() or None
        if self.acquired:
            if self.revision is None or self.revision < 1:
                raise ValueError("acquired claim requires revision")
            if reason is not None:
                raise ValueError("acquired claim cannot contain reason")
        elif reason is None:
            raise ValueError("unacquired claim requires reason")
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class RecoveryOrderRecord:
    order_id: str
    generation: int
    status: TrackedOrderStatus
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        order_id = str(self.order_id or "").strip()
        if not order_id:
            raise ValueError("order_id is required")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 0
        ):
            raise ValueError("generation cannot be negative")
        if not isinstance(self.status, TrackedOrderStatus):
            object.__setattr__(
                self,
                "status",
                TrackedOrderStatus(str(self.status).upper()),
            )
        quantity = self.quantity
        if quantity is not None:
            quantity = Decimal(str(quantity))
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError("quantity must be positive")
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "quantity", quantity)


@dataclass(frozen=True)
class ReconciliationCandidate:
    group: OrderGroupRecord
    orders: tuple[RecoveryOrderRecord, ...]
    interrupted_event_id: str | None = None
    interrupted_event_status: SupervisionEventStatus | None = None
    interrupted_claimed_revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.group, OrderGroupRecord):
            raise TypeError("group must be an OrderGroupRecord")
        if self.group.status not in {
            OrderGroupStatus.FAILED,
            OrderGroupStatus.REPRICING,
        }:
            raise ValueError(
                "reconciliation candidate must be failed or repricing"
            )
        orders = tuple(self.orders)
        if not orders or any(
            not isinstance(order, RecoveryOrderRecord)
            for order in orders
        ):
            raise ValueError(
                "reconciliation candidate requires tracked orders"
            )
        order_ids = tuple(order.order_id for order in orders)
        if len(order_ids) != len(set(order_ids)):
            raise ValueError(
                "reconciliation candidate order ids must be unique"
            )
        allowed_generations = {
            self.group.reprice_count,
            self.group.reprice_count + 1,
        }
        if any(
            order.generation not in allowed_generations
            for order in orders
        ):
            raise ValueError(
                "reconciliation candidate contains an unrelated generation"
            )
        if not any(
            order.generation == self.group.reprice_count
            for order in orders
        ):
            raise ValueError(
                "reconciliation candidate has no source generation"
            )

        event_id = (
            str(self.interrupted_event_id or "").strip()
            or None
        )
        event_status = self.interrupted_event_status
        claimed_revision = self.interrupted_claimed_revision
        if claimed_revision is not None:
            if isinstance(claimed_revision, bool):
                raise ValueError(
                    "interrupted claimed revision must be positive"
                )
            claimed_revision = int(claimed_revision)
            if claimed_revision < 1:
                raise ValueError(
                    "interrupted claimed revision must be positive"
                )
        if event_status is not None and not isinstance(
            event_status,
            SupervisionEventStatus,
        ):
            event_status = SupervisionEventStatus(
                str(event_status).upper()
            )
        if event_id is None:
            if event_status is not None or claimed_revision is not None:
                raise ValueError(
                    "interrupted event details require an event id"
                )
        else:
            if event_status not in {
                SupervisionEventStatus.CLAIMED,
                SupervisionEventStatus.FAILED,
            }:
                raise ValueError(
                    "interrupted event must be claimed or failed"
                )
            if (
                event_status == SupervisionEventStatus.CLAIMED
                and (
                    claimed_revision is None
                    or claimed_revision < 1
                )
            ):
                raise ValueError(
                    "claimed interrupted event requires a revision"
                )
        object.__setattr__(self, "orders", orders)
        object.__setattr__(
            self,
            "interrupted_event_id",
            event_id,
        )
        object.__setattr__(
            self,
            "interrupted_event_status",
            event_status,
        )
        object.__setattr__(
            self,
            "interrupted_claimed_revision",
            claimed_revision,
        )


def registration_from_handle(
    handle: ExecutionHandle,
    *,
    policy: OrderLifecyclePolicy,
    metadata: Mapping[str, Any] | None = None,
) -> OrderGroupRegistration:
    if isinstance(policy, KeepOpenPolicy):
        policy_kind = policy.kind
        old_tick = None
        new_tick = None
        max_reprices = 0
    elif isinstance(policy, RepriceOnTickChange):
        policy_kind = policy.kind
        old_tick = policy.old_tick
        new_tick = policy.new_tick
        max_reprices = policy.max_reprices
    else:
        raise TypeError("unsupported order lifecycle policy")

    return OrderGroupRegistration(
        order_group_id=handle.order_group_id,
        intent_id=handle.intent_id,
        signal_id=handle.signal_id,
        template_id=handle.template_id,
        strategy_id=handle.strategy_id,
        account_name=handle.account_name,
        condition_id=handle.condition_id,
        outcome=handle.outcome,
        asset_id=handle.asset_id,
        side=handle.side,
        desired_price=handle.desired_price,
        quantity=handle.quantity,
        notional=handle.notional,
        policy_kind=policy_kind,
        trigger_old_tick=old_tick,
        trigger_new_tick=new_tick,
        max_reprices=max_reprices,
        initial_order_ids=handle.live_order_ids,
        metadata=metadata or {},
    )
