from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Protocol, Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle


@dataclass(frozen=True)
class TickSizeChange:
    event_id: str
    asset_id: str
    old_tick: Decimal
    new_tick: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        event_id = self.event_id.strip()
        asset_id = self.asset_id.strip()
        if not event_id:
            raise ValueError("event_id is required")
        if not asset_id:
            raise ValueError("asset_id is required")

        old_tick = Decimal(str(self.old_tick))
        new_tick = Decimal(str(self.new_tick))
        if old_tick <= 0 or new_tick <= 0:
            raise ValueError("tick sizes must be positive")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(self, "old_tick", old_tick)
        object.__setattr__(self, "new_tick", new_tick)
        object.__setattr__(
            self,
            "observed_at",
            self.observed_at.astimezone(timezone.utc),
        )


class SupervisionStatus(str, Enum):
    IGNORED = "IGNORED"
    REPLACED = "REPLACED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SupervisionResult:
    event_id: str
    order_group_id: str
    status: SupervisionStatus
    cancelled_order_ids: tuple[str, ...] = ()
    replacement_order_ids: tuple[str, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "order_group_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if not isinstance(self.status, SupervisionStatus):
            object.__setattr__(
                self,
                "status",
                SupervisionStatus(str(self.status).upper()),
            )
        object.__setattr__(
            self,
            "cancelled_order_ids",
            tuple(self.cancelled_order_ids),
        )
        object.__setattr__(
            self,
            "replacement_order_ids",
            tuple(self.replacement_order_ids),
        )
        error = str(self.error or "").strip() or None
        if self.status == SupervisionStatus.REPLACED:
            if not self.cancelled_order_ids or not self.replacement_order_ids:
                raise ValueError(
                    "replaced supervision result requires cancelled and replacement orders"
                )
        if self.status == SupervisionStatus.FAILED and not error:
            raise ValueError("failed supervision result requires error")
        object.__setattr__(self, "error", error)


class OrderSupervisor(Protocol):
    """Own post-submission cancel/replace for registered execution groups."""

    def register(
        self,
        handle: ExecutionHandle,
        *,
        policy: OrderLifecyclePolicy,
    ) -> None: ...

    def on_tick_size_change(
        self,
        event: TickSizeChange,
    ) -> Sequence[SupervisionResult]: ...

    def reconcile(self) -> Sequence[SupervisionResult]: ...

    def close(self) -> None: ...
