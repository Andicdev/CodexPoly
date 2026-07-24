from __future__ import annotations

import threading
from decimal import Decimal
from typing import Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle, PlacedOrder
from cbr_trading.execution.order_group_repository import (
    OrderGroupRepository,
)
from cbr_trading.execution.order_group_state import (
    OrderGroupRecord,
    SupervisionClaim,
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
    """Claim, cancel, replace, and persist one owned order group at a time."""

    def __init__(
        self,
        *,
        repository: OrderGroupRepository,
        gateway: SupervisionOrderGateway,
    ):
        self._repository = repository
        self._gateway = gateway
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
        """Background recovery is separate; tick repricing reconciles inline."""

        with self._lock:
            self._require_open()
            return ()

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
        try:
            if not group.live_order_ids:
                raise RuntimeError("order_group_has_no_live_orders")

            pre_inspection = self._gateway.inspect_orders(
                account_name=group.registration.account_name,
                order_ids=group.live_order_ids,
            )
            pre_snapshots = _validated_inspection(
                pre_inspection,
                requested_order_ids=group.live_order_ids,
                group=group,
            )
            observations = tuple(
                OrderObservation(
                    phase=OrderObservationPhase.PRE_CANCEL,
                    snapshot=snapshot,
                )
                for snapshot in pre_snapshots
            )
            if pre_inspection.failed_order_ids:
                raise RuntimeError(
                    pre_inspection.error
                    or "one_or_more_order_inspections_failed"
                )
            _require_known_states(pre_snapshots)
            _validate_original_sizing(
                pre_snapshots,
                group=group,
            )

            pre_by_id = {
                snapshot.order_id: snapshot
                for snapshot in pre_snapshots
            }
            filled = tuple(
                order_id
                for order_id in group.live_order_ids
                if (
                    pre_by_id[order_id].state
                    == RemoteOrderState.FILLED
                )
            )
            cancelled = tuple(
                order_id
                for order_id in group.live_order_ids
                if (
                    pre_by_id[order_id].state
                    == RemoteOrderState.CANCELLED
                )
            )
            open_order_ids = tuple(
                order_id
                for order_id in group.live_order_ids
                if (
                    pre_by_id[order_id].state
                    == RemoteOrderState.OPEN
                )
            )

            post_snapshots: tuple[RemoteOrderSnapshot, ...] = ()
            if open_order_ids:
                cancellation = self._gateway.cancel_orders(
                    account_name=group.registration.account_name,
                    order_ids=open_order_ids,
                )
                if not isinstance(cancellation, CancellationResult):
                    raise TypeError(
                        "gateway returned invalid cancellation result"
                    )
                if (
                    set(cancellation.requested_order_ids)
                    != set(open_order_ids)
                ):
                    raise ValueError(
                        "gateway cancellation scope does not match "
                        "open group orders"
                    )
                cancelled = _unique_ids(
                    cancelled,
                    cancellation.cancelled_order_ids,
                )
                if cancellation.failed_order_ids:
                    raise RuntimeError(
                        cancellation.error
                        or "one_or_more_cancellations_failed"
                    )

                post_inspection = self._gateway.inspect_orders(
                    account_name=group.registration.account_name,
                    order_ids=open_order_ids,
                )
                post_snapshots = _validated_inspection(
                    post_inspection,
                    requested_order_ids=open_order_ids,
                    group=group,
                )
                observations = (
                    *observations,
                    *(
                        OrderObservation(
                            phase=OrderObservationPhase.POST_CANCEL,
                            snapshot=snapshot,
                        )
                        for snapshot in post_snapshots
                    ),
                )
                if post_inspection.failed_order_ids:
                    raise RuntimeError(
                        post_inspection.error
                        or "post_cancel_order_inspection_failed"
                    )
                _require_terminal_states(post_snapshots)

            final_by_id = {
                snapshot.order_id: snapshot
                for snapshot in pre_snapshots
                if snapshot.order_id not in set(open_order_ids)
            }
            final_by_id.update(
                {
                    snapshot.order_id: snapshot
                    for snapshot in post_snapshots
                }
            )
            if set(final_by_id) != set(group.live_order_ids):
                raise ValueError(
                    "final remote order state is incomplete"
                )
            final_filled = tuple(
                order_id
                for order_id in group.live_order_ids
                if (
                    final_by_id[order_id].state
                    == RemoteOrderState.FILLED
                )
            )
            final_cancelled = tuple(
                order_id
                for order_id in group.live_order_ids
                if (
                    final_by_id[order_id].state
                    == RemoteOrderState.CANCELLED
                )
            )
            (
                remaining_quantity,
                remaining_notional,
            ) = _remaining_sizing(
                group,
                final_by_id=final_by_id,
                cancelled_order_ids=final_cancelled,
            )
            filled = final_filled
            cancelled = final_cancelled

            if (
                remaining_quantity is None
                and remaining_notional is None
            ):
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
            if not cancelled:
                raise ValueError(
                    "remaining sizing has no cancelled source orders"
                )

            request = _replacement_request(
                group,
                cancelled_order_ids=cancelled,
                remaining_quantity=remaining_quantity,
                remaining_notional=remaining_notional,
            )
            replacements = tuple(
                self._gateway.place_replacement(request)
            )
            _validate_replacements(
                replacements,
                request=request,
            )
            self._repository.complete_reprice(
                claim,
                cancelled_order_ids=cancelled,
                filled_order_ids=filled,
                replacement_orders=replacements,
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
            error = redact_exception(exc)
            persistence_error = _fail_claim_safely(
                self._repository,
                claim,
                error=error,
                cancelled_order_ids=cancelled,
                filled_order_ids=filled,
                replacement_orders=replacements,
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
