from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle, PlacedOrder
from cbr_trading.execution.order_group_repository import (
    OrderGroupRepository,
)
from cbr_trading.execution.order_group_state import (
    OrderGroupRecord,
    ReconciliationCandidate,
    RecoveryOrderRecord,
    SupervisionClaim,
    TrackedOrderStatus,
)
from cbr_trading.execution.order_supervisor import (
    SupervisionResult,
    SupervisionStatus,
    TickSizeChange,
)
from cbr_trading.execution.supervision_gateway import (
    CancellationResult,
    OrderInspectionResult,
    OrderObservation,
    OrderObservationPhase,
    RemoteOrderSnapshot,
    RemoteOrderState,
    ReplacementOrderRequest,
    SupervisionOrderGateway,
    replacement_price_for_tick,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)


class OrderSupervisorError(RuntimeError):
    """Sanitized failure at the supervisor service boundary."""


class PersistentOrderSupervisor:
    """Persist tick repricing and recover tracked interrupted order groups."""

    def __init__(
        self,
        *,
        repository: OrderGroupRepository,
        gateway: SupervisionOrderGateway,
        reconciliation_stale_after: timedelta = timedelta(
            minutes=5
        ),
        reconciliation_batch_size: int = 100,
        preinspect_after: timedelta = timedelta(seconds=5),
        clock: Callable[[], datetime] | None = None,
    ):
        if (
            not isinstance(reconciliation_stale_after, timedelta)
            or reconciliation_stale_after <= timedelta(0)
        ):
            raise ValueError(
                "reconciliation_stale_after must be positive"
            )
        if (
            isinstance(reconciliation_batch_size, bool)
            or not isinstance(reconciliation_batch_size, int)
            or reconciliation_batch_size < 1
            or reconciliation_batch_size > 1000
        ):
            raise ValueError(
                "reconciliation_batch_size must be between 1 and 1000"
            )
        if (
            not isinstance(preinspect_after, timedelta)
            or preinspect_after <= timedelta(0)
        ):
            raise ValueError("preinspect_after must be positive")
        self._repository = repository
        self._gateway = gateway
        self._reconciliation_stale_after = (
            reconciliation_stale_after
        )
        self._reconciliation_batch_size = (
            reconciliation_batch_size
        )
        self._preinspect_after = preinspect_after
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._closed = False

    def register(
        self,
        handle: ExecutionHandle,
        *,
        policy: OrderLifecyclePolicy,
    ) -> None:
        with self._lock:
            self._require_open()
            try:
                self._repository.register(handle, policy=policy)
            except Exception as exc:
                raise OrderSupervisorError(
                    redact_exception(exc)
                ) from None

    def on_tick_size_change(
        self,
        event: TickSizeChange,
    ) -> tuple[SupervisionResult, ...]:
        with self._lock:
            self._require_open()
            try:
                groups = tuple(
                    self._repository.load_active_for_asset(
                        event.asset_id
                    )
                )
            except Exception as exc:
                raise OrderSupervisorError(
                    redact_exception(exc)
                ) from None

            return tuple(
                self._process_group(group, event=event)
                for group in groups
            )

    def reconcile(self) -> tuple[SupervisionResult, ...]:
        with self._lock:
            self._require_open()
            observed_at = _aware_utc(
                self._clock(),
                name="reconciliation clock",
            )
            try:
                candidates = tuple(
                    self._repository.load_reconciliation_candidates(
                        stale_before=(
                            observed_at
                            - self._reconciliation_stale_after
                        ),
                        limit=self._reconciliation_batch_size,
                    )
                )
            except Exception as exc:
                raise OrderSupervisorError(
                    redact_exception(exc)
                ) from None
            return tuple(
                self._reconcile_candidate(
                    candidate,
                    observed_at=observed_at,
                )
                for candidate in candidates
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            gateway_error: Exception | None = None
            try:
                self._gateway.close()
            except Exception as exc:
                gateway_error = exc
            try:
                self._repository.close()
            except Exception as exc:
                if gateway_error is None:
                    gateway_error = exc
            if gateway_error is not None:
                raise OrderSupervisorError(
                    redact_exception(gateway_error)
                ) from None

    def _process_group(
        self,
        group: OrderGroupRecord,
        *,
        event: TickSizeChange,
    ) -> SupervisionResult:
        try:
            claim = self._repository.claim_tick_size_change(
                order_group_id=group.registration.order_group_id,
                event=event,
            )
        except Exception as exc:
            return _failed_result(
                event,
                group,
                error=redact_exception(exc),
            )
        if not claim.acquired:
            return SupervisionResult(
                event_id=event.event_id,
                order_group_id=group.registration.order_group_id,
                status=SupervisionStatus.IGNORED,
                error=claim.reason,
            )

        cancelled: tuple[str, ...] = ()
        filled: tuple[str, ...] = ()
        replacements: tuple[PlacedOrder, ...] = ()
        observations: tuple[OrderObservation, ...] = ()
        replacement_persisted = False
        replacement_quantity = group.registration.quantity
        replacement_notional = group.registration.notional
        cancellation_targets = group.live_order_ids
        stage = "stale_source_preinspection"
        try:
            if not group.live_order_ids:
                raise RuntimeError("order_group_has_no_live_orders")

            if self._requires_preinspection(group, event=event):
                inspection = self._gateway.inspect_orders(
                    account_name=group.registration.account_name,
                    order_ids=group.live_order_ids,
                )
                snapshots = _validated_inspection(
                    inspection,
                    requested_order_ids=group.live_order_ids,
                    group=group,
                )
                if inspection.failed_order_ids:
                    raise RuntimeError(
                        inspection.error
                        or "stale_source_preinspection_failed"
                    )
                _require_known_states(snapshots)
                _validate_original_sizing(snapshots, group=group)
                observations = tuple(
                    OrderObservation(
                        phase=OrderObservationPhase.PRE_CANCEL,
                        snapshot=snapshot,
                    )
                    for snapshot in snapshots
                )
                filled = tuple(
                    snapshot.order_id
                    for snapshot in snapshots
                    if snapshot.state == RemoteOrderState.FILLED
                )
                cancelled = tuple(
                    snapshot.order_id
                    for snapshot in snapshots
                    if snapshot.state == RemoteOrderState.CANCELLED
                )
                cancellation_targets = tuple(
                    snapshot.order_id
                    for snapshot in snapshots
                    if snapshot.state == RemoteOrderState.OPEN
                )
                (
                    replacement_quantity,
                    replacement_notional,
                ) = _remaining_from_snapshots(group, snapshots=snapshots)
                if (
                    replacement_quantity is None
                    and replacement_notional is None
                ):
                    stage = "filled_source_completion"
                    self._repository.complete_without_replacement(
                        claim,
                        filled_order_ids=filled,
                        cancelled_order_ids=cancelled,
                        observations=observations,
                    )
                    return SupervisionResult(
                        event_id=event.event_id,
                        order_group_id=(
                            group.registration.order_group_id
                        ),
                        status=SupervisionStatus.COMPLETED,
                    )

            stage = "replacement_request"
            request = _replacement_request(
                group,
                cancelled_order_ids=group.live_order_ids,
                remaining_quantity=replacement_quantity,
                remaining_notional=replacement_notional,
            )
            stage = "replacement_submission"
            replacements = tuple(
                self._gateway.place_replacement(request)
            )
            stage = "replacement_validation"
            _validate_replacements(
                replacements,
                request=request,
            )

            # The target-tick order is the only latency-sensitive market
            # operation.  Persist its acknowledged ID before any lookup or
            # cancellation of the source order.  This intentionally accepts
            # a short overlap between the 0.99 and 0.999 orders.
            stage = "replacement_persistence"
            self._repository.record_replacement_submission(
                claim,
                replacement_orders=replacements,
                parent_order_ids=group.live_order_ids,
            )
            replacement_persisted = True

            stage = "source_cancellation"
            if cancellation_targets:
                cancellation = self._gateway.cancel_orders(
                    account_name=group.registration.account_name,
                    order_ids=cancellation_targets,
                )
                if not isinstance(cancellation, CancellationResult):
                    raise TypeError(
                        "gateway returned invalid cancellation result"
                    )
                if set(cancellation.requested_order_ids) != set(
                    cancellation_targets
                ):
                    raise ValueError(
                        "gateway cancellation scope does not match "
                        "source group orders"
                    )
                confirmed_cancelled = set(
                    cancellation.cancelled_order_ids
                )
                cancelled = _unique_ids(
                    cancelled,
                    tuple(
                        order_id
                        for order_id in cancellation_targets
                        if order_id in confirmed_cancelled
                    ),
                )
                if cancellation.failed_order_ids:
                    raise RuntimeError(
                        cancellation.error
                        or "one_or_more_cancellations_failed"
                    )

            stage = "completion_persistence"
            self._repository.complete_reprice(
                claim,
                cancelled_order_ids=cancelled,
                replacement_orders=replacements,
                filled_order_ids=filled,
                observations=observations,
            )
            return SupervisionResult(
                event_id=event.event_id,
                order_group_id=group.registration.order_group_id,
                status=SupervisionStatus.REPLACED,
                cancelled_order_ids=cancelled,
                replacement_order_ids=tuple(
                    order.order_id
                    for order in replacements
                ),
            )
        except Exception as exc:
            error = _stage_error(stage, redact_exception(exc))
            persistence_error = _fail_claim_safely(
                self._repository,
                claim,
                error=error,
                cancelled_order_ids=cancelled,
                filled_order_ids=filled,
                replacement_orders=(
                    ()
                    if replacement_persisted
                    else replacements
                ),
                observations=observations,
            )
            if persistence_error is not None:
                error = redact_sensitive_text(
                    f"{error}; persistence={persistence_error}",
                    max_length=500,
                )
            return _failed_result(
                event,
                group,
                error=error,
                cancelled_order_ids=cancelled,
                replacement_order_ids=tuple(
                    order.order_id
                    for order in replacements
                ),
            )

    def _requires_preinspection(
        self,
        group: OrderGroupRecord,
        *,
        event: TickSizeChange,
    ) -> bool:
        submit_first = group.registration.metadata.get(
            "submit_first_repricing",
            True,
        )
        if not isinstance(submit_first, bool):
            raise ValueError(
                "submit_first_repricing metadata must be a bool"
            )
        if not submit_first:
            return True
        created_at = group.created_at
        if created_at is None:
            return False
        return event.observed_at - created_at >= self._preinspect_after

    def _reconcile_candidate(
        self,
        candidate: ReconciliationCandidate,
        *,
        observed_at: datetime,
    ) -> SupervisionResult:
        if not isinstance(candidate, ReconciliationCandidate):
            raise TypeError(
                "repository returned an invalid reconciliation "
                "candidate"
            )
        group = candidate.group
        event_id = _reconciliation_event_id(candidate)
        try:
            claim = self._repository.claim_reconciliation(
                candidate,
                event_id=event_id,
                observed_at=observed_at,
            )
        except Exception as exc:
            return _reconciliation_result(
                event_id,
                group,
                status=SupervisionStatus.FAILED,
                error=redact_exception(exc),
            )
        if not claim.acquired:
            return _reconciliation_result(
                event_id,
                group,
                status=SupervisionStatus.IGNORED,
                error=claim.reason,
            )

        observations: tuple[OrderObservation, ...] = ()
        order_statuses: dict[str, TrackedOrderStatus] = {}
        try:
            order_ids = tuple(
                order.order_id
                for order in candidate.orders
            )
            inspection = self._gateway.inspect_orders(
                account_name=group.registration.account_name,
                order_ids=order_ids,
            )
            snapshots = _validated_inspection(
                inspection,
                requested_order_ids=order_ids,
                group=group,
            )
            observations = tuple(
                OrderObservation(
                    phase=OrderObservationPhase.RECONCILE,
                    snapshot=snapshot,
                )
                for snapshot in snapshots
            )
            order_statuses = {
                snapshot.order_id: _tracked_status_for_snapshot(
                    snapshot
                )
                for snapshot in snapshots
            }
            if inspection.failed_order_ids:
                raise RuntimeError(
                    inspection.error
                    or "reconciliation_order_inspection_failed"
                )
            _require_known_states(snapshots)

            snapshots_by_id = {
                snapshot.order_id: snapshot
                for snapshot in snapshots
            }
            source_orders = tuple(
                order
                for order in candidate.orders
                if order.generation == group.reprice_count
            )
            replacement_orders = tuple(
                order
                for order in candidate.orders
                if (
                    order.generation
                    == group.reprice_count + 1
                )
            )
            if not replacement_orders:
                return self._manual_review_result(
                    claim,
                    group=group,
                    error=(
                        "replacement_order_id_not_persisted;"
                        "duplicate_replacement_cannot_be_excluded"
                    ),
                    order_statuses=order_statuses,
                    observations=observations,
                )

            source_snapshots = tuple(
                snapshots_by_id[order.order_id]
                for order in source_orders
            )
            replacement_snapshots = tuple(
                snapshots_by_id[order.order_id]
                for order in replacement_orders
            )
            _validate_original_sizing(
                source_snapshots,
                group=group,
            )
            if any(
                snapshot.state
                not in {
                    RemoteOrderState.CANCELLED,
                    RemoteOrderState.FILLED,
                }
                for snapshot in source_snapshots
            ):
                return self._manual_review_result(
                    claim,
                    group=group,
                    error=(
                        "source_and_replacement_orders_are_not_"
                        "safely_separated"
                    ),
                    order_statuses=order_statuses,
                    observations=observations,
                )

            terminal_overfill = _terminal_overfill(
                source_snapshots=source_snapshots,
                replacement_snapshots=replacement_snapshots,
            )
            if terminal_overfill is not None:
                target_quantity, filled_quantity, excess_quantity = (
                    terminal_overfill
                )
                for snapshot in source_snapshots:
                    order_statuses[snapshot.order_id] = (
                        TrackedOrderStatus.FILLED
                        if snapshot.state == RemoteOrderState.FILLED
                        else TrackedOrderStatus.REPLACED
                    )
                self._repository.complete_overfill_reconciliation(
                    claim,
                    order_statuses=order_statuses,
                    target_quantity=target_quantity,
                    filled_quantity=filled_quantity,
                    excess_quantity=excess_quantity,
                    detected_at=observed_at,
                    observations=observations,
                )
                return _reconciliation_result(
                    event_id,
                    group,
                    status=SupervisionStatus.COMPLETED,
                    cancelled_order_ids=tuple(
                        snapshot.order_id
                        for snapshot in source_snapshots
                        if (
                            snapshot.state
                            == RemoteOrderState.CANCELLED
                        )
                    ),
                    replacement_order_ids=tuple(
                        order.order_id
                        for order in replacement_orders
                    ),
                    error=(
                        "overfill_detected:"
                        f"target={target_quantity};"
                        f"filled={filled_quantity};"
                        f"excess={excess_quantity}"
                    ),
                )

            try:
                _validate_recovered_replacement(
                    group,
                    source_orders=source_orders,
                    source_snapshots=source_snapshots,
                    replacement_orders=replacement_orders,
                    replacement_snapshots=replacement_snapshots,
                )
            except (ArithmeticError, ValueError) as exc:
                return self._manual_review_result(
                    claim,
                    group=group,
                    error=redact_exception(exc),
                    order_statuses=order_statuses,
                    observations=observations,
                )
            for snapshot in source_snapshots:
                order_statuses[snapshot.order_id] = (
                    TrackedOrderStatus.FILLED
                    if snapshot.state == RemoteOrderState.FILLED
                    else TrackedOrderStatus.REPLACED
                )

            live_replacement_ids = tuple(
                snapshot.order_id
                for snapshot in replacement_snapshots
                if snapshot.state == RemoteOrderState.OPEN
            )
            keep_active = (
                bool(live_replacement_ids)
                and group.reprice_count + 1
                < group.registration.max_reprices
            )
            self._repository.complete_reconciliation(
                claim,
                order_statuses=order_statuses,
                recovered_reprice=True,
                keep_active=keep_active,
                observations=observations,
            )
            cancelled_source_ids = tuple(
                snapshot.order_id
                for snapshot in source_snapshots
                if snapshot.state == RemoteOrderState.CANCELLED
            )
            replacement_ids = tuple(
                order.order_id
                for order in replacement_orders
            )
            return _reconciliation_result(
                event_id,
                group,
                status=(
                    SupervisionStatus.REPLACED
                    if live_replacement_ids
                    else SupervisionStatus.COMPLETED
                ),
                cancelled_order_ids=cancelled_source_ids,
                replacement_order_ids=replacement_ids,
            )
        except Exception as exc:
            error = redact_exception(exc)
            persistence_error = _fail_reconciliation_safely(
                self._repository,
                claim,
                error=error,
                order_statuses=order_statuses,
                observations=observations,
                manual_review=False,
            )
            if persistence_error is not None:
                error = redact_sensitive_text(
                    f"{error}; persistence={persistence_error}",
                    max_length=500,
                )
            return _reconciliation_result(
                event_id,
                group,
                status=SupervisionStatus.FAILED,
                error=error,
            )

    def _manual_review_result(
        self,
        claim: SupervisionClaim,
        *,
        group: OrderGroupRecord,
        error: str,
        order_statuses: Mapping[str, TrackedOrderStatus],
        observations: Sequence[OrderObservation],
    ) -> SupervisionResult:
        persistence_error = _fail_reconciliation_safely(
            self._repository,
            claim,
            error=error,
            order_statuses=order_statuses,
            observations=observations,
            manual_review=True,
        )
        if persistence_error is not None:
            error = redact_sensitive_text(
                f"{error}; persistence={persistence_error}",
                max_length=500,
            )
        return _reconciliation_result(
            claim.event_id,
            group,
            status=SupervisionStatus.FAILED,
            error=error,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise OrderSupervisorError("order supervisor is closed")


def _replacement_request(
    group: OrderGroupRecord,
    *,
    cancelled_order_ids: Sequence[str],
    remaining_quantity: Decimal | None,
    remaining_notional: Decimal | None,
) -> ReplacementOrderRequest:
    registration = group.registration
    if (
        registration.side is None
        or registration.desired_price is None
        or registration.trigger_new_tick is None
    ):
        raise ValueError(
            "order group lacks replacement order parameters"
        )
    effective_price = replacement_price_for_tick(
        registration.desired_price,
        tick_size=registration.trigger_new_tick,
        side=registration.side,
    )
    return ReplacementOrderRequest(
        order_group_id=registration.order_group_id,
        account_name=registration.account_name,
        condition_id=registration.condition_id,
        outcome=registration.outcome,
        asset_id=registration.asset_id,
        side=registration.side,
        limit_price=effective_price,
        tick_size=registration.trigger_new_tick,
        quantity=remaining_quantity,
        notional=remaining_notional,
        replaced_order_ids=tuple(cancelled_order_ids),
    )


def _stage_error(stage: str, error: str) -> str:
    safe_stage = str(stage or "").strip().casefold()
    if not safe_stage:
        safe_stage = "unknown"
    return redact_sensitive_text(
        f"stage={safe_stage}; {error}",
        max_length=500,
    )


def _validate_replacements(
    replacements: Sequence[PlacedOrder],
    *,
    request: ReplacementOrderRequest,
) -> None:
    if not replacements:
        raise ValueError("gateway returned no replacement orders")
    if any(
        not isinstance(order, PlacedOrder)
        for order in replacements
    ):
        raise TypeError(
            "gateway replacements must contain PlacedOrder objects"
        )
    order_ids = [order.order_id for order in replacements]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("gateway returned duplicate replacement order ids")
    if any(
        order.asset_id != request.asset_id
        for order in replacements
    ):
        raise ValueError("gateway returned a replacement for another asset")
    if any(
        order.effective_price != request.limit_price
        for order in replacements
    ):
        raise ValueError(
            "gateway replacement price does not match requested price"
        )
    if request.quantity is not None:
        expected_quantity = request.quantity
    elif request.notional is not None:
        expected_quantity = (
            request.notional / request.limit_price
        )
    else:
        raise ValueError("replacement request sizing is missing")
    if sum(
        (order.quantity for order in replacements),
        Decimal("0"),
    ) != expected_quantity:
        raise ValueError(
            "gateway replacement quantity does not match remaining quantity"
        )


def _fail_claim_safely(
    repository: OrderGroupRepository,
    claim: SupervisionClaim,
    *,
    error: str,
    cancelled_order_ids: Sequence[str],
    filled_order_ids: Sequence[str],
    replacement_orders: Sequence[PlacedOrder],
    observations: Sequence[OrderObservation],
) -> str | None:
    try:
        repository.fail_claim(
            claim,
            error=error,
            cancelled_order_ids=cancelled_order_ids,
            filled_order_ids=filled_order_ids,
            replacement_orders=replacement_orders,
            observations=observations,
        )
        return None
    except Exception as exc:
        return redact_exception(exc)


def _fail_reconciliation_safely(
    repository: OrderGroupRepository,
    claim: SupervisionClaim,
    *,
    error: str,
    order_statuses: Mapping[str, TrackedOrderStatus],
    observations: Sequence[OrderObservation],
    manual_review: bool,
) -> str | None:
    try:
        repository.fail_reconciliation(
            claim,
            error=error,
            order_statuses=order_statuses,
            observations=observations,
            manual_review=manual_review,
        )
        return None
    except Exception as exc:
        return redact_exception(exc)


def _failed_result(
    event: TickSizeChange,
    group: OrderGroupRecord,
    *,
    error: str,
    cancelled_order_ids: Sequence[str] = (),
    replacement_order_ids: Sequence[str] = (),
) -> SupervisionResult:
    return SupervisionResult(
        event_id=event.event_id,
        order_group_id=group.registration.order_group_id,
        status=SupervisionStatus.FAILED,
        cancelled_order_ids=tuple(cancelled_order_ids),
        replacement_order_ids=tuple(replacement_order_ids),
        error=redact_sensitive_text(error, max_length=500),
    )


def _reconciliation_result(
    event_id: str,
    group: OrderGroupRecord,
    *,
    status: SupervisionStatus,
    cancelled_order_ids: Sequence[str] = (),
    replacement_order_ids: Sequence[str] = (),
    error: str | None = None,
) -> SupervisionResult:
    return SupervisionResult(
        event_id=event_id,
        order_group_id=group.registration.order_group_id,
        status=status,
        cancelled_order_ids=tuple(cancelled_order_ids),
        replacement_order_ids=tuple(replacement_order_ids),
        error=(
            redact_sensitive_text(error, max_length=500)
            if error
            else None
        ),
    )


def _validated_inspection(
    inspection: object,
    *,
    requested_order_ids: Sequence[str],
    group: OrderGroupRecord,
) -> tuple[RemoteOrderSnapshot, ...]:
    if not isinstance(inspection, OrderInspectionResult):
        raise TypeError(
            "gateway returned invalid order inspection result"
        )
    if set(inspection.requested_order_ids) != set(
        requested_order_ids
    ):
        raise ValueError(
            "gateway inspection scope does not match order group"
        )
    registration = group.registration
    for snapshot in inspection.snapshots:
        if (
            snapshot.condition_id.casefold()
            != registration.condition_id.casefold()
            or snapshot.asset_id != registration.asset_id
            or snapshot.side != registration.side
        ):
            raise ValueError(
                "remote order ownership does not match order group"
            )
    return inspection.snapshots


def _require_known_states(
    snapshots: Sequence[RemoteOrderSnapshot],
) -> None:
    if any(
        snapshot.state == RemoteOrderState.UNKNOWN
        for snapshot in snapshots
    ):
        raise ValueError("remote order state is unknown")


def _require_terminal_states(
    snapshots: Sequence[RemoteOrderSnapshot],
) -> None:
    if any(
        snapshot.state not in {
            RemoteOrderState.CANCELLED,
            RemoteOrderState.FILLED,
        }
        for snapshot in snapshots
    ):
        raise ValueError(
            "post-cancel remote order state is not terminal"
        )


def _unique_ids(
    *groups: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            order_id
            for group in groups
            for order_id in group
        )
    )


def _validate_original_sizing(
    snapshots: Sequence[RemoteOrderSnapshot],
    *,
    group: OrderGroupRecord,
) -> None:
    registration = group.registration
    if registration.quantity is not None:
        remote_quantity = sum(
            (
                snapshot.original_quantity
                for snapshot in snapshots
            ),
            Decimal("0"),
        )
        if remote_quantity != registration.quantity:
            raise ValueError(
                "remote original quantity does not match order group"
            )
        return
    if registration.notional is None:
        raise ValueError("order group sizing is missing")
    remote_notional = sum(
        (
            snapshot.original_quantity * snapshot.limit_price
            for snapshot in snapshots
        ),
        Decimal("0"),
    )
    if remote_notional > registration.notional:
        raise ValueError(
            "remote original notional exceeds order group"
        )


def _remaining_sizing(
    group: OrderGroupRecord,
    *,
    final_by_id: dict[str, RemoteOrderSnapshot],
    cancelled_order_ids: Sequence[str],
) -> tuple[Decimal | None, Decimal | None]:
    registration = group.registration
    if registration.quantity is not None:
        remaining_quantity = sum(
            (
                final_by_id[order_id].remaining_quantity
                for order_id in cancelled_order_ids
            ),
            Decimal("0"),
        )
        if remaining_quantity == 0:
            return None, None
        return remaining_quantity, None

    if registration.notional is None:
        raise ValueError("order group sizing is missing")
    remaining_notional = sum(
        (
            final_by_id[order_id].remaining_quantity
            * final_by_id[order_id].limit_price
            for order_id in cancelled_order_ids
        ),
        Decimal("0"),
    )
    if remaining_notional == 0:
        return None, None
    return None, remaining_notional


def _remaining_from_snapshots(
    group: OrderGroupRecord,
    *,
    snapshots: Sequence[RemoteOrderSnapshot],
) -> tuple[Decimal | None, Decimal | None]:
    registration = group.registration
    if registration.quantity is not None:
        remaining_quantity = sum(
            (
                snapshot.remaining_quantity
                for snapshot in snapshots
            ),
            Decimal("0"),
        )
        if remaining_quantity == 0:
            return None, None
        return remaining_quantity, None

    if registration.notional is None:
        raise ValueError("order group sizing is missing")
    remaining_notional = sum(
        (
            snapshot.remaining_quantity * snapshot.limit_price
            for snapshot in snapshots
        ),
        Decimal("0"),
    )
    if remaining_notional == 0:
        return None, None
    return None, remaining_notional


def _validate_recovered_replacement(
    group: OrderGroupRecord,
    *,
    source_orders: Sequence[RecoveryOrderRecord],
    source_snapshots: Sequence[RemoteOrderSnapshot],
    replacement_orders: Sequence[RecoveryOrderRecord],
    replacement_snapshots: Sequence[RemoteOrderSnapshot],
) -> None:
    if not source_orders or not replacement_orders:
        raise ValueError(
            "recovered reprice requires source and replacement orders"
        )
    registration = group.registration
    if (
        registration.side is None
        or registration.desired_price is None
        or registration.trigger_new_tick is None
    ):
        raise ValueError(
            "order group lacks replacement order parameters"
        )
    target_price = replacement_price_for_tick(
        registration.desired_price,
        tick_size=registration.trigger_new_tick,
        side=registration.side,
    )
    if any(
        snapshot.limit_price != target_price
        for snapshot in replacement_snapshots
    ):
        raise ValueError(
            "recovered replacement price does not match target price"
        )
    tracked_by_id = {
        order.order_id: order
        for order in replacement_orders
    }
    for snapshot in replacement_snapshots:
        tracked_quantity = tracked_by_id[
            snapshot.order_id
        ].quantity
        if (
            tracked_quantity is None
            or tracked_quantity
            != snapshot.original_quantity
        ):
            raise ValueError(
                "recovered replacement quantity does not match "
                "persisted order"
            )

    source_remaining_quantity = sum(
        (
            snapshot.remaining_quantity
            for snapshot in source_snapshots
            if snapshot.state == RemoteOrderState.CANCELLED
        ),
        Decimal("0"),
    )
    if registration.quantity is not None:
        expected_quantity = source_remaining_quantity
    elif registration.notional is not None:
        remaining_notional = sum(
            (
                snapshot.remaining_quantity
                * snapshot.limit_price
                for snapshot in source_snapshots
                if snapshot.state
                == RemoteOrderState.CANCELLED
            ),
            Decimal("0"),
        )
        expected_quantity = remaining_notional / target_price
    else:
        raise ValueError("order group sizing is missing")
    actual_quantity = sum(
        (
            snapshot.original_quantity
            for snapshot in replacement_snapshots
        ),
        Decimal("0"),
    )
    if expected_quantity <= 0 or actual_quantity != expected_quantity:
        raise ValueError(
            "recovered replacement does not match final source "
            "remainder"
        )


def _tracked_status_for_snapshot(
    snapshot: RemoteOrderSnapshot,
) -> TrackedOrderStatus:
    return {
        RemoteOrderState.OPEN: TrackedOrderStatus.LIVE,
        RemoteOrderState.CANCELLED: (
            TrackedOrderStatus.CANCELLED
        ),
        RemoteOrderState.FILLED: TrackedOrderStatus.FILLED,
        RemoteOrderState.UNKNOWN: TrackedOrderStatus.UNKNOWN,
    }[snapshot.state]


def _terminal_overfill(
    *,
    source_snapshots: Sequence[RemoteOrderSnapshot],
    replacement_snapshots: Sequence[RemoteOrderSnapshot],
) -> tuple[Decimal, Decimal, Decimal] | None:
    snapshots = tuple(source_snapshots) + tuple(
        replacement_snapshots
    )
    if not source_snapshots or not replacement_snapshots:
        return None
    if any(
        snapshot.state
        not in {
            RemoteOrderState.CANCELLED,
            RemoteOrderState.FILLED,
        }
        for snapshot in snapshots
    ):
        return None
    target_quantity = sum(
        (
            snapshot.original_quantity
            for snapshot in source_snapshots
        ),
        Decimal("0"),
    )
    filled_quantity = sum(
        (
            snapshot.matched_quantity
            for snapshot in snapshots
        ),
        Decimal("0"),
    )
    if filled_quantity <= target_quantity:
        return None
    return (
        target_quantity,
        filled_quantity,
        filled_quantity - target_quantity,
    )


def _reconciliation_event_id(
    candidate: ReconciliationCandidate,
) -> str:
    group = candidate.group
    return (
        "reconcile:"
        f"{group.registration.order_group_id}:"
        f"{group.revision}"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
