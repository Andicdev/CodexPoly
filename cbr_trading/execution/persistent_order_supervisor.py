from __future__ import annotations

import threading
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
        """Reconciliation is a separate checkpoint; no live scan occurs yet."""

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
        replacements: tuple[PlacedOrder, ...] = ()
        try:
            if not group.live_order_ids:
                raise RuntimeError("order_group_has_no_live_orders")
            cancellation = self._gateway.cancel_orders(
                account_name=group.registration.account_name,
                order_ids=group.live_order_ids,
            )
            if not isinstance(cancellation, CancellationResult):
                raise TypeError(
                    "gateway returned invalid cancellation result"
                )
            if (
                set(cancellation.requested_order_ids)
                != set(group.live_order_ids)
            ):
                raise ValueError(
                    "gateway cancellation scope does not match order group"
                )
            cancelled = cancellation.cancelled_order_ids
            if cancellation.failed_order_ids:
                raise RuntimeError(
                    cancellation.error
                    or "one_or_more_cancellations_failed"
                )

            request = _replacement_request(
                group,
                cancelled_order_ids=cancelled,
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
                replacement_orders=replacements,
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
                replacement_orders=replacements,
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
        quantity=registration.quantity,
        notional=registration.notional,
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


def _fail_claim_safely(
    repository: OrderGroupRepository,
    claim: SupervisionClaim,
    *,
    error: str,
    cancelled_order_ids: Sequence[str],
    replacement_orders: Sequence[PlacedOrder],
) -> str | None:
    try:
        repository.fail_claim(
            claim,
            error=error,
            cancelled_order_ids=cancelled_order_ids,
            replacement_orders=replacement_orders,
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
