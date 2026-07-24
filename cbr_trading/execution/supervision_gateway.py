from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from typing import Protocol, Sequence

from cbr_trading.domain.intents import OrderSide, Outcome
from cbr_trading.domain.results import PlacedOrder


class RemoteOrderState(str, Enum):
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"
    FILLED = "FILLED"
    UNKNOWN = "UNKNOWN"


class OrderObservationPhase(str, Enum):
    PRE_CANCEL = "PRE_CANCEL"
    POST_CANCEL = "POST_CANCEL"
    RECONCILE = "RECONCILE"


@dataclass(frozen=True)
class RemoteOrderSnapshot:
    order_id: str
    condition_id: str
    asset_id: str
    side: OrderSide
    limit_price: Decimal
    original_quantity: Decimal
    matched_quantity: Decimal
    state: RemoteOrderState
    remote_status: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "order_id",
            "condition_id",
            "asset_id",
            "remote_status",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if not isinstance(self.side, OrderSide):
            object.__setattr__(
                self,
                "side",
                OrderSide(str(self.side).upper()),
            )
        if not isinstance(self.state, RemoteOrderState):
            object.__setattr__(
                self,
                "state",
                RemoteOrderState(str(self.state).upper()),
            )

        price = Decimal(str(self.limit_price))
        original = Decimal(str(self.original_quantity))
        matched = Decimal(str(self.matched_quantity))
        if (
            not price.is_finite()
            or price <= 0
            or price >= 1
            or not original.is_finite()
            or original <= 0
            or not matched.is_finite()
            or matched < 0
            or matched > original
        ):
            raise ValueError("invalid remote order quantities")
        remaining = original - matched
        if self.state == RemoteOrderState.FILLED and remaining != 0:
            raise ValueError(
                "filled remote order must have no remaining quantity"
            )
        if self.state in {
            RemoteOrderState.OPEN,
            RemoteOrderState.CANCELLED,
        } and remaining <= 0:
            raise ValueError(
                "open or cancelled remote order must have remaining quantity"
            )
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "original_quantity", original)
        object.__setattr__(self, "matched_quantity", matched)
        object.__setattr__(self, "limit_price", price)
        object.__setattr__(
            self,
            "observed_at",
            self.observed_at.astimezone(timezone.utc),
        )

    @property
    def remaining_quantity(self) -> Decimal:
        return self.original_quantity - self.matched_quantity


@dataclass(frozen=True)
class OrderInspectionResult:
    requested_order_ids: tuple[str, ...]
    snapshots: tuple[RemoteOrderSnapshot, ...]
    failed_order_ids: tuple[str, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        requested = _normalized_ids(
            self.requested_order_ids,
            name="requested_order_ids",
            required=True,
        )
        snapshots = tuple(self.snapshots)
        if any(
            not isinstance(snapshot, RemoteOrderSnapshot)
            for snapshot in snapshots
        ):
            raise TypeError(
                "snapshots must contain RemoteOrderSnapshot objects"
            )
        snapshot_ids = tuple(
            snapshot.order_id
            for snapshot in snapshots
        )
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("snapshot order ids must be unique")
        failed = _normalized_ids(
            self.failed_order_ids,
            name="failed_order_ids",
            required=False,
        )
        if set(snapshot_ids) & set(failed):
            raise ValueError(
                "inspected and failed order ids must be disjoint"
            )
        if set(snapshot_ids) | set(failed) != set(requested):
            raise ValueError(
                "inspection result must account for every requested order"
            )
        error = str(self.error or "").strip() or None
        if failed and error is None:
            raise ValueError(
                "failed inspection result requires an error"
            )
        object.__setattr__(self, "requested_order_ids", requested)
        object.__setattr__(self, "snapshots", snapshots)
        object.__setattr__(self, "failed_order_ids", failed)
        object.__setattr__(self, "error", error)


@dataclass(frozen=True)
class OrderObservation:
    phase: OrderObservationPhase
    snapshot: RemoteOrderSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.phase, OrderObservationPhase):
            object.__setattr__(
                self,
                "phase",
                OrderObservationPhase(str(self.phase).upper()),
            )
        if not isinstance(self.snapshot, RemoteOrderSnapshot):
            raise TypeError(
                "snapshot must be a RemoteOrderSnapshot"
            )


@dataclass(frozen=True)
class CancellationResult:
    requested_order_ids: tuple[str, ...]
    cancelled_order_ids: tuple[str, ...]
    failed_order_ids: tuple[str, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "requested_order_ids",
            "cancelled_order_ids",
            "failed_order_ids",
        ):
            values = tuple(
                str(value or "").strip()
                for value in getattr(self, name)
            )
            if any(not value for value in values):
                raise ValueError(f"{name} cannot contain empty values")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, values)

        requested = set(self.requested_order_ids)
        cancelled = set(self.cancelled_order_ids)
        failed = set(self.failed_order_ids)
        if not requested:
            raise ValueError("requested_order_ids must not be empty")
        if cancelled & failed:
            raise ValueError(
                "cancelled and failed order ids must be disjoint"
            )
        if cancelled | failed != requested:
            raise ValueError(
                "cancellation result must account for every requested order"
            )
        error = str(self.error or "").strip() or None
        if failed and error is None:
            raise ValueError(
                "failed cancellation result requires an error"
            )
        object.__setattr__(self, "error", error)


@dataclass(frozen=True)
class ReplacementOrderRequest:
    order_group_id: str
    account_name: str
    condition_id: str
    outcome: Outcome
    asset_id: str
    side: OrderSide
    limit_price: Decimal
    tick_size: Decimal
    replaced_order_ids: tuple[str, ...]
    quantity: Decimal | None = None
    notional: Decimal | None = None

    def __post_init__(self) -> None:
        for name in (
            "order_group_id",
            "account_name",
            "condition_id",
            "asset_id",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if not isinstance(self.outcome, Outcome):
            object.__setattr__(
                self,
                "outcome",
                Outcome(str(self.outcome).upper()),
            )
        if not isinstance(self.side, OrderSide):
            object.__setattr__(
                self,
                "side",
                OrderSide(str(self.side).upper()),
            )

        price = Decimal(str(self.limit_price))
        tick = Decimal(str(self.tick_size))
        if price <= 0 or price >= 1:
            raise ValueError("limit_price must be between 0 and 1")
        if tick <= 0:
            raise ValueError("tick_size must be positive")
        if price / tick != (price / tick).to_integral_value():
            raise ValueError("limit_price must align with tick_size")
        object.__setattr__(self, "limit_price", price)
        object.__setattr__(self, "tick_size", tick)

        quantity = (
            Decimal(str(self.quantity))
            if self.quantity is not None
            else None
        )
        notional = (
            Decimal(str(self.notional))
            if self.notional is not None
            else None
        )
        if (quantity is None) == (notional is None):
            raise ValueError(
                "exactly one of quantity or notional is required"
            )
        if quantity is not None and quantity <= 0:
            raise ValueError("quantity must be positive")
        if notional is not None and notional <= 0:
            raise ValueError("notional must be positive")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "notional", notional)

        replaced = tuple(
            str(value or "").strip()
            for value in self.replaced_order_ids
        )
        if not replaced or any(not value for value in replaced):
            raise ValueError("replaced_order_ids must not be empty")
        if len(replaced) != len(set(replaced)):
            raise ValueError("replaced_order_ids must be unique")
        object.__setattr__(self, "replaced_order_ids", replaced)


class SupervisionOrderGateway(Protocol):
    """Exact-order cancellation and replacement boundary."""

    def inspect_orders(
        self,
        *,
        account_name: str,
        order_ids: Sequence[str],
    ) -> OrderInspectionResult: ...

    def cancel_orders(
        self,
        *,
        account_name: str,
        order_ids: Sequence[str],
    ) -> CancellationResult: ...

    def place_replacement(
        self,
        request: ReplacementOrderRequest,
    ) -> Sequence[PlacedOrder]: ...

    def close(self) -> None: ...


def replacement_price_for_tick(
    desired_price: Decimal,
    *,
    tick_size: Decimal,
    side: OrderSide,
) -> Decimal:
    desired = Decimal(str(desired_price))
    tick = Decimal(str(tick_size))
    if desired <= 0 or desired >= 1:
        raise ValueError("desired_price must be between 0 and 1")
    if tick <= 0:
        raise ValueError("tick_size must be positive")
    normalized_side = (
        side
        if isinstance(side, OrderSide)
        else OrderSide(str(side).upper())
    )
    rounding = (
        ROUND_FLOOR
        if normalized_side == OrderSide.BUY
        else ROUND_CEILING
    )
    units = (desired / tick).to_integral_value(rounding=rounding)
    effective = units * tick
    if effective <= 0 or effective >= 1:
        raise ValueError(
            "desired price cannot be represented by the target tick"
        )
    return effective


def _normalized_ids(
    values: Sequence[str],
    *,
    name: str,
    required: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence, not a string")
    normalized = tuple(
        str(value or "").strip()
        for value in values
    )
    if any(not value for value in normalized):
        raise ValueError(f"{name} cannot contain empty values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must be unique")
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized
