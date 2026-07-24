from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle, PlacedOrder
from cbr_trading.execution.order_group_state import (
    OrderGroupRecord,
    SupervisionClaim,
)
from cbr_trading.execution.order_supervisor import TickSizeChange
from cbr_trading.execution.supervision_gateway import (
    OrderObservation,
)


class OrderGroupRepository(Protocol):
    """Persistence boundary used by the persistent OrderSupervisor."""

    def ensure_ready(self) -> None: ...

    def register(
        self,
        handle: ExecutionHandle,
        *,
        policy: OrderLifecyclePolicy,
        metadata: Mapping[str, object] | None = None,
    ) -> OrderGroupRecord: ...

    def load_active_for_asset(
        self,
        asset_id: str,
    ) -> Sequence[OrderGroupRecord]: ...

    def claim_tick_size_change(
        self,
        *,
        order_group_id: str,
        event: TickSizeChange,
    ) -> SupervisionClaim: ...

    def fail_claim(
        self,
        claim: SupervisionClaim,
        *,
        error: str,
        cancelled_order_ids: Sequence[str] = (),
        filled_order_ids: Sequence[str] = (),
        replacement_orders: Sequence[PlacedOrder] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None: ...

    def complete_reprice(
        self,
        claim: SupervisionClaim,
        *,
        cancelled_order_ids: Sequence[str],
        replacement_orders: Sequence[PlacedOrder],
        filled_order_ids: Sequence[str] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None: ...

    def complete_without_replacement(
        self,
        claim: SupervisionClaim,
        *,
        filled_order_ids: Sequence[str],
        cancelled_order_ids: Sequence[str] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None: ...

    def close(self) -> None: ...
