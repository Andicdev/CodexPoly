from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Protocol, Sequence

from cbr_trading.domain.intents import OrderSide, Outcome
from cbr_trading.domain.results import PlacedOrder


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
