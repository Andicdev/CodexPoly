from __future__ import annotations

from datetime import datetime
from typing import Mapping, Protocol, Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle, PlacedOrder
from cbr_trading.execution.order_group_state import (
    OrderGroupRecord,
    ReconciliationCandidate,
    SupervisionClaim,
    TrackedOrderStatus,
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

    def load_reconciliation_candidates(
        self,
        *,
        stale_before: datetime,
        limit: int = 100,
    ) -> Sequence[ReconciliationCandidate]: ...

    def claim_reconciliation(
        self,
        candidate: ReconciliationCandidate,
        *,
        event_id: str,
        observed_at: datetime,
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

    def complete_reconciliation(
        self,
        claim: SupervisionClaim,
        *,
        order_statuses: Mapping[str, TrackedOrderStatus],
        recovered_reprice: bool,
        keep_active: bool,
        observations: Sequence[OrderObservation] = (),
    ) -> None: ...

    def fail_reconciliation(
        self,
        claim: SupervisionClaim,
        *,
        error: str,
        order_statuses: Mapping[str, TrackedOrderStatus] | None = None,
        observations: Sequence[OrderObservation] = (),
        manual_review: bool = False,
    ) -> None: ...

    def close(self) -> None: ...
