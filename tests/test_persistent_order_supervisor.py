from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.domain import (
    ExecutionHandle,
    OrderSide,
    Outcome,
    PlacedOrder,
    RepriceOnTickChange,
)
from cbr_trading.execution import (
    CancellationResult,
    OrderInspectionResult,
    OrderGroupRecord,
    OrderGroupStatus,
    OrderObservationPhase,
    OrderSupervisorError,
    PersistentOrderSupervisor,
    ReconciliationCandidate,
    RecoveryOrderRecord,
    RemoteOrderSnapshot,
    RemoteOrderState,
    SupervisionClaim,
    SupervisionEventStatus,
    SupervisionStatus,
    TickSizeChange,
    TrackedOrderStatus,
    registration_from_handle,
    replacement_price_for_tick,
)


def _handle(
    *,
    live_order_ids: tuple[str, ...] = ("order-1",),
) -> ExecutionHandle:
    return ExecutionHandle(
        order_group_id="group-1",
        intent_id="signal-1/template-1",
        account_name="primary",
        condition_id="condition-1",
        outcome=Outcome.YES,
        asset_id="asset-yes",
        live_order_ids=live_order_ids,
        signal_id="signal-1",
        template_id="template-1",
        strategy_id="strategy-1",
        side=OrderSide.BUY,
        desired_price=Decimal("0.999"),
        quantity=Decimal("25"),
    )


def _policy() -> RepriceOnTickChange:
    return RepriceOnTickChange(
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
        max_reprices=1,
    )


def _record(
    *,
    live_order_ids: tuple[str, ...] = ("order-1",),
    status: OrderGroupStatus = OrderGroupStatus.ACTIVE,
    revision: int = 0,
    reprice_count: int = 0,
    created_at: datetime | None = None,
) -> OrderGroupRecord:
    return OrderGroupRecord(
        registration=registration_from_handle(
            _handle(
                live_order_ids=(
                    live_order_ids or ("order-1",)
                )
            ),
            policy=_policy(),
        ),
        status=status,
        revision=revision,
        reprice_count=reprice_count,
        live_order_ids=live_order_ids,
        created_at=created_at,
    )


def _notional_record() -> OrderGroupRecord:
    handle = ExecutionHandle(
        order_group_id="group-1",
        intent_id="signal-1/template-1",
        account_name="primary",
        condition_id="condition-1",
        outcome=Outcome.YES,
        asset_id="asset-yes",
        live_order_ids=("order-1",),
        signal_id="signal-1",
        template_id="template-1",
        strategy_id="strategy-1",
        side=OrderSide.BUY,
        desired_price=Decimal("0.999"),
        notional=Decimal("10"),
    )
    return OrderGroupRecord(
        registration=registration_from_handle(
            handle,
            policy=_policy(),
        ),
        status=OrderGroupStatus.ACTIVE,
        revision=0,
        reprice_count=0,
        live_order_ids=("order-1",),
    )


def _event() -> TickSizeChange:
    return TickSizeChange(
        event_id="tick-event-1",
        asset_id="asset-yes",
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
        observed_at=datetime(
            2026,
            7,
            24,
            13,
            30,
            tzinfo=timezone.utc,
        ),
    )


def _replacement(
    *,
    order_id: str = "order-2",
    quantity: Decimal = Decimal("25"),
) -> PlacedOrder:
    return PlacedOrder(
        order_id=order_id,
        asset_id="asset-yes",
        effective_price=Decimal("0.999"),
        quantity=quantity,
    )


def _snapshot(
    order_id: str,
    *,
    state: RemoteOrderState,
    original: Decimal = Decimal("25"),
    matched: Decimal = Decimal("0"),
    limit_price: Decimal = Decimal("0.99"),
) -> RemoteOrderSnapshot:
    return RemoteOrderSnapshot(
        order_id=order_id,
        condition_id="condition-1",
        asset_id="asset-yes",
        side=OrderSide.BUY,
        limit_price=limit_price,
        original_quantity=original,
        matched_quantity=matched,
        state=state,
        remote_status=state.value,
        observed_at=datetime(
            2026,
            7,
            24,
            13,
            31,
            tzinfo=timezone.utc,
        ),
    )


def _inspection(
    order_ids: tuple[str, ...],
    *,
    state: RemoteOrderState,
    original: Decimal = Decimal("25"),
    matched: Decimal = Decimal("0"),
    limit_price: Decimal = Decimal("0.99"),
) -> OrderInspectionResult:
    return OrderInspectionResult(
        requested_order_ids=order_ids,
        snapshots=tuple(
            _snapshot(
                order_id,
                state=state,
                original=original,
                matched=matched,
                limit_price=limit_price,
            )
            for order_id in order_ids
        ),
    )


def _reconciliation_candidate(
    *,
    source_status: TrackedOrderStatus = (
        TrackedOrderStatus.CANCELLED
    ),
    include_replacement: bool = True,
    replacement_status: TrackedOrderStatus = (
        TrackedOrderStatus.UNKNOWN
    ),
) -> ReconciliationCandidate:
    orders = [
        RecoveryOrderRecord(
            order_id="order-1",
            generation=0,
            status=source_status,
            quantity=Decimal("25"),
        )
    ]
    if include_replacement:
        orders.append(
            RecoveryOrderRecord(
                order_id="order-2",
                generation=1,
                status=replacement_status,
                quantity=Decimal("20"),
            )
        )
    return ReconciliationCandidate(
        group=_record(
            live_order_ids=(
                ("order-1",)
                if source_status == TrackedOrderStatus.LIVE
                else ()
            ),
            status=OrderGroupStatus.FAILED,
            revision=2,
        ),
        orders=tuple(orders),
        interrupted_event_id="tick-event-1",
        interrupted_event_status=(
            SupervisionEventStatus.FAILED
        ),
        interrupted_claimed_revision=1,
    )


class _Repository:
    def __init__(
        self,
        *,
        groups=(),
        claim: SupervisionClaim | None = None,
        reconciliation_candidates=(),
        reconciliation_claim: SupervisionClaim | None = None,
    ):
        self.groups = tuple(groups)
        self.claim = claim or SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )
        self.reconciliation_candidates = tuple(
            reconciliation_candidates
        )
        self.reconciliation_claim = (
            reconciliation_claim
            or SupervisionClaim(
                event_id="reconcile:group-1:2",
                order_group_id="group-1",
                acquired=True,
                revision=3,
            )
        )
        self.register_calls = []
        self.load_calls = []
        self.claim_calls = []
        self.record_replacement_calls = []
        self.complete_calls = []
        self.complete_without_calls = []
        self.fail_calls = []
        self.load_reconciliation_calls = []
        self.claim_reconciliation_calls = []
        self.complete_reconciliation_calls = []
        self.fail_reconciliation_calls = []
        self.close_calls = 0
        self.complete_error: Exception | None = None
        self.record_replacement_error: Exception | None = None
        self.load_reconciliation_error: Exception | None = None

    def register(self, handle, *, policy, metadata=None):
        self.register_calls.append((handle, policy, metadata))
        return _record(live_order_ids=handle.live_order_ids)

    def load_active_for_asset(self, asset_id):
        self.load_calls.append(asset_id)
        return self.groups

    def claim_tick_size_change(self, *, order_group_id, event):
        self.claim_calls.append((order_group_id, event))
        return self.claim

    def load_reconciliation_candidates(
        self,
        *,
        stale_before,
        limit=100,
    ):
        self.load_reconciliation_calls.append(
            (stale_before, limit)
        )
        if self.load_reconciliation_error is not None:
            raise self.load_reconciliation_error
        return self.reconciliation_candidates

    def claim_reconciliation(
        self,
        candidate,
        *,
        event_id,
        observed_at,
    ):
        self.claim_reconciliation_calls.append(
            (candidate, event_id, observed_at)
        )
        return self.reconciliation_claim

    def complete_reprice(
        self,
        claim,
        *,
        cancelled_order_ids,
        replacement_orders,
        filled_order_ids=(),
        observations=(),
    ):
        self.complete_calls.append(
            (
                claim,
                tuple(cancelled_order_ids),
                tuple(replacement_orders),
                tuple(filled_order_ids),
                tuple(observations),
            )
        )
        if self.complete_error is not None:
            raise self.complete_error

    def record_replacement_submission(
        self,
        claim,
        *,
        replacement_orders,
        parent_order_ids,
    ):
        self.record_replacement_calls.append(
            (
                claim,
                tuple(replacement_orders),
                tuple(parent_order_ids),
            )
        )
        if self.record_replacement_error is not None:
            raise self.record_replacement_error

    def fail_claim(
        self,
        claim,
        *,
        error,
        cancelled_order_ids=(),
        filled_order_ids=(),
        replacement_orders=(),
        observations=(),
    ):
        self.fail_calls.append(
            (
                claim,
                error,
                tuple(cancelled_order_ids),
                tuple(replacement_orders),
                tuple(filled_order_ids),
                tuple(observations),
            )
        )

    def complete_without_replacement(
        self,
        claim,
        *,
        filled_order_ids,
        cancelled_order_ids=(),
        observations=(),
    ):
        self.complete_without_calls.append(
            (
                claim,
                tuple(filled_order_ids),
                tuple(cancelled_order_ids),
                tuple(observations),
            )
        )
        if self.complete_error is not None:
            raise self.complete_error

    def complete_reconciliation(
        self,
        claim,
        *,
        order_statuses,
        recovered_reprice,
        keep_active,
        observations=(),
    ):
        self.complete_reconciliation_calls.append(
            (
                claim,
                dict(order_statuses),
                recovered_reprice,
                keep_active,
                tuple(observations),
            )
        )
        if self.complete_error is not None:
            raise self.complete_error

    def fail_reconciliation(
        self,
        claim,
        *,
        error,
        order_statuses=None,
        observations=(),
        manual_review=False,
    ):
        self.fail_reconciliation_calls.append(
            (
                claim,
                error,
                dict(order_statuses or {}),
                tuple(observations),
                manual_review,
            )
        )

    def close(self):
        self.close_calls += 1


class _Gateway:
    def __init__(
        self,
        *,
        cancellation: CancellationResult | None = None,
        replacements=(),
        inspections=(),
    ):
        self.cancellation = cancellation or CancellationResult(
            requested_order_ids=("order-1",),
            cancelled_order_ids=("order-1",),
        )
        self.replacements = tuple(replacements)
        self.inspections = list(inspections)
        self.inspect_calls = []
        self.cancel_calls = []
        self.place_calls = []
        self.operations = []
        self.close_calls = 0

    def inspect_orders(self, *, account_name, order_ids):
        normalized = tuple(order_ids)
        self.inspect_calls.append((account_name, normalized))
        self.operations.append(("inspect", normalized))
        if self.inspections:
            return self.inspections.pop(0)
        per_order = Decimal("25") / Decimal(len(normalized))
        state = (
            RemoteOrderState.OPEN
            if len(self.inspect_calls) % 2 == 1
            else RemoteOrderState.CANCELLED
        )
        return _inspection(
            normalized,
            state=state,
            original=per_order,
        )

    def cancel_orders(self, *, account_name, order_ids):
        self.cancel_calls.append((account_name, tuple(order_ids)))
        self.operations.append(("cancel", tuple(order_ids)))
        return self.cancellation

    def place_replacement(self, request):
        self.place_calls.append(request)
        self.operations.append(
            ("place", request.replaced_order_ids)
        )
        return self.replacements

    def close(self):
        self.close_calls += 1


class ReplacementPriceTests(unittest.TestCase):
    def test_buy_price_floors_to_valid_tick(self) -> None:
        self.assertEqual(
            replacement_price_for_tick(
                Decimal("0.999"),
                tick_size=Decimal("0.01"),
                side=OrderSide.BUY,
            ),
            Decimal("0.99"),
        )

    def test_sell_price_ceilings_to_valid_tick(self) -> None:
        self.assertEqual(
            replacement_price_for_tick(
                Decimal("0.981"),
                tick_size=Decimal("0.01"),
                side=OrderSide.SELL,
            ),
            Decimal("0.99"),
        )


class PersistentOrderSupervisorTests(unittest.TestCase):
    def test_register_delegates_owned_group_to_repository(self) -> None:
        repository = _Repository()
        gateway = _Gateway()
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        supervisor.register(_handle(), policy=_policy())

        self.assertEqual(len(repository.register_calls), 1)
        self.assertEqual(
            repository.register_calls[0][0].order_group_id,
            "group-1",
        )

    def test_success_cancels_only_owned_ids_and_persists_replacement(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(replacements=(_replacement(),))
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, SupervisionStatus.REPLACED)
        self.assertEqual(
            gateway.cancel_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(
            gateway.operations,
            [
                ("place", ("order-1",)),
                ("cancel", ("order-1",)),
            ],
        )
        self.assertEqual(gateway.inspect_calls, [])
        request = gateway.place_calls[0]
        self.assertEqual(request.replaced_order_ids, ("order-1",))
        self.assertEqual(request.limit_price, Decimal("0.999"))
        self.assertEqual(
            repository.complete_calls[0][1],
            ("order-1",),
        )
        self.assertEqual(
            repository.complete_calls[0][2][0].order_id,
            "order-2",
        )
        self.assertEqual(
            repository.record_replacement_calls[0][1],
            (_replacement(),),
        )
        self.assertEqual(
            repository.record_replacement_calls[0][2],
            ("order-1",),
        )
        self.assertEqual(repository.complete_calls[0][4], ())
        self.assertEqual(repository.fail_calls, [])

    def test_unrelated_asset_has_no_market_side_effects(self) -> None:
        repository = _Repository(groups=())
        gateway = _Gateway(replacements=(_replacement(),))
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results, ())
        self.assertEqual(repository.load_calls, ["asset-yes"])
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(gateway.inspect_calls, [])

    def test_duplicate_event_is_ignored_before_market_calls(self) -> None:
        repository = _Repository(
            groups=(_record(),),
            claim=SupervisionClaim(
                event_id="tick-event-1",
                order_group_id="group-1",
                acquired=False,
                reason="duplicate_event:completed",
            ),
        )
        gateway = _Gateway(replacements=(_replacement(),))
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.IGNORED)
        self.assertEqual(
            results[0].error,
            "duplicate_event:completed",
        )
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(gateway.inspect_calls, [])

    def test_partial_cancel_persists_already_placed_replacement(
        self,
    ) -> None:
        live_ids = ("order-1", "order-2")
        repository = _Repository(
            groups=(_record(live_order_ids=live_ids),)
        )
        gateway = _Gateway(
            cancellation=CancellationResult(
                requested_order_ids=live_ids,
                cancelled_order_ids=("order-1",),
                failed_order_ids=("order-2",),
                error="order-2 cancellation failed",
            ),
            replacements=(_replacement(order_id="order-3"),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertEqual(
            results[0].cancelled_order_ids,
            ("order-1",),
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(
            repository.fail_calls[0][2],
            ("order-1",),
        )
        self.assertEqual(
            repository.record_replacement_calls[0][1][0].order_id,
            "order-3",
        )
        self.assertEqual(repository.fail_calls[0][3], ())
        self.assertIn(
            "stage=source_cancellation",
            results[0].error,
        )

    def test_completion_failure_tracks_unknown_replacement(self) -> None:
        repository = _Repository(groups=(_record(),))
        repository.complete_error = RuntimeError(
            "replacement state commit failed"
        )
        replacement = _replacement()
        gateway = _Gateway(replacements=(replacement,))
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertEqual(
            results[0].replacement_order_ids,
            ("order-2",),
        )
        self.assertEqual(
            repository.fail_calls[0][2],
            ("order-1",),
        )
        self.assertEqual(
            repository.record_replacement_calls[0][1],
            (replacement,),
        )
        self.assertEqual(repository.fail_calls[0][3], ())
        self.assertIn(
            "stage=completion_persistence",
            results[0].error,
        )

    def test_submission_persistence_failure_uses_fail_safe_insert(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        repository.record_replacement_error = RuntimeError(
            "replacement acknowledgement commit failed"
        )
        replacement = _replacement()
        gateway = _Gateway(replacements=(replacement,))
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(
            repository.fail_calls[0][3],
            (replacement,),
        )
        self.assertIn(
            "stage=replacement_persistence",
            results[0].error,
        )

    def test_gateway_cannot_expand_cancellation_scope(self) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            cancellation=CancellationResult(
                requested_order_ids=("foreign-order",),
                cancelled_order_ids=("foreign-order",),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertIn("scope", results[0].error)
        self.assertEqual(
            gateway.cancel_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(
            repository.record_replacement_calls[0][1],
            (_replacement(),),
        )
        self.assertEqual(repository.fail_calls[0][3], ())
        self.assertEqual(repository.fail_calls[0][2], ())

    def test_gateway_may_report_same_scope_in_different_order(self) -> None:
        live_ids = ("order-1", "order-2")
        repository = _Repository(
            groups=(_record(live_order_ids=live_ids),)
        )
        replacement = _replacement(order_id="order-3")
        gateway = _Gateway(
            cancellation=CancellationResult(
                requested_order_ids=("order-2", "order-1"),
                cancelled_order_ids=("order-2", "order-1"),
            ),
            replacements=(replacement,),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.REPLACED)
        self.assertEqual(
            repository.complete_calls[0][1],
            ("order-1", "order-2"),
        )

    def test_reprice_does_not_wait_for_preinspection(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        replacement = _replacement(quantity=Decimal("25"))
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=("order-1",),
                    snapshots=(),
                    failed_order_ids=("order-1",),
                    error="temporary lookup failure",
                ),
            ),
            replacements=(replacement,),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.REPLACED)
        self.assertEqual(
            gateway.place_calls[0].quantity,
            Decimal("25"),
        )
        self.assertEqual(gateway.inspect_calls, [])
        self.assertEqual(
            repository.complete_calls[0][2],
            (replacement,),
        )

    def test_replacement_is_recorded_before_cleanup_completes(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        replacement = _replacement(quantity=Decimal("25"))
        gateway = _Gateway(
            replacements=(replacement,),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(gateway.inspect_calls, [])
        self.assertEqual(
            repository.record_replacement_calls[0][1],
            (replacement,),
        )
        self.assertEqual(repository.complete_calls[0][2], (replacement,))

    def test_notional_sizing_uses_full_registered_notional(
        self,
    ) -> None:
        repository = _Repository(groups=(_notional_record(),))
        remaining_notional = Decimal("10")
        replacement_quantity = (
            remaining_notional / Decimal("0.999")
        )
        replacement = _replacement(
            quantity=replacement_quantity
        )
        gateway = _Gateway(
            replacements=(replacement,),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.REPLACED)
        request = gateway.place_calls[0]
        self.assertIsNone(request.quantity)
        self.assertEqual(request.notional, remaining_notional)
        self.assertEqual(
            repository.complete_calls[0][2],
            (replacement,),
        )

    def test_tick_change_never_blocks_on_remote_fill_lookup(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.FILLED,
                    original=Decimal("25"),
                    matched=Decimal("25"),
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(
            gateway.cancel_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(gateway.inspect_calls, [])

    def test_stale_group_filled_before_tick_skips_replacement(
        self,
    ) -> None:
        group = _record(
            created_at=_event().observed_at - timedelta(minutes=8)
        )
        repository = _Repository(groups=(group,))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.FILLED,
                    original=Decimal("25"),
                    matched=Decimal("25"),
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.COMPLETED,
        )
        self.assertEqual(
            gateway.inspect_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(
            repository.complete_without_calls[0][1],
            ("order-1",),
        )
        self.assertEqual(
            repository.complete_without_calls[0][3][0].phase,
            OrderObservationPhase.PRE_CANCEL,
        )

    def test_stale_partial_fill_replaces_only_remaining_quantity(
        self,
    ) -> None:
        group = _record(
            created_at=_event().observed_at - timedelta(minutes=8)
        )
        repository = _Repository(groups=(group,))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                    original=Decimal("25"),
                    matched=Decimal("10"),
                ),
            ),
            replacements=(
                _replacement(quantity=Decimal("15")),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(
            gateway.place_calls[0].quantity,
            Decimal("15"),
        )
        self.assertEqual(
            gateway.cancel_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(
            repository.complete_calls[0][4][0].phase,
            OrderObservationPhase.PRE_CANCEL,
        )

    def test_stale_preinspection_failure_fails_closed(
        self,
    ) -> None:
        group = _record(
            created_at=_event().observed_at - timedelta(minutes=8)
        )
        repository = _Repository(groups=(group,))
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=("order-1",),
                    snapshots=(),
                    failed_order_ids=("order-1",),
                    error="temporary lookup failure",
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.FAILED,
        )
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(gateway.cancel_calls, [])
        self.assertIn(
            "stage=stale_source_preinspection",
            results[0].error,
        )

    def test_does_not_read_unconfirmed_post_cancel_state(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                ),
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(len(gateway.inspect_calls), 0)

    def test_does_not_make_post_cancel_lookup(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                ),
                OrderInspectionResult(
                    requested_order_ids=("order-1",),
                    snapshots=(),
                    failed_order_ids=("order-1",),
                    error="post-cancel lookup unavailable",
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(len(gateway.place_calls), 1)
        self.assertEqual(len(gateway.inspect_calls), 0)
        self.assertEqual(repository.fail_calls, [])

    def test_remote_quantity_lookup_is_not_in_hot_path(self) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                    original=Decimal("30"),
                ),
            ),
            replacements=(_replacement(),),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.on_tick_size_change(_event())

        self.assertEqual(results[0].status, SupervisionStatus.REPLACED)
        self.assertEqual(gateway.inspect_calls, [])
        self.assertEqual(
            gateway.cancel_calls,
            [("primary", ("order-1",))],
        )
        self.assertEqual(len(gateway.place_calls), 1)

    def test_reconcile_recovers_persisted_unknown_replacement(
        self,
    ) -> None:
        candidate = _reconciliation_candidate()
        repository = _Repository(
            reconciliation_candidates=(candidate,)
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.OPEN,
                            original=Decimal("20"),
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        now = datetime(
            2026,
            7,
            24,
            14,
            0,
            tzinfo=timezone.utc,
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
            clock=lambda: now,
            reconciliation_stale_after=timedelta(minutes=5),
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(
            repository.load_reconciliation_calls,
            [(now - timedelta(minutes=5), 100)],
        )
        completed = repository.complete_reconciliation_calls[0]
        self.assertEqual(
            completed[1],
            {
                "order-1": TrackedOrderStatus.REPLACED,
                "order-2": TrackedOrderStatus.LIVE,
            },
        )
        self.assertTrue(completed[2])
        self.assertFalse(completed[3])
        self.assertTrue(
            all(
                observation.phase
                == OrderObservationPhase.RECONCILE
                for observation in completed[4]
            )
        )

    def test_reconcile_completes_filled_unknown_replacement(
        self,
    ) -> None:
        repository = _Repository(
            reconciliation_candidates=(
                _reconciliation_candidate(),
            )
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.FILLED,
                            original=Decimal("20"),
                            matched=Decimal("20"),
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.COMPLETED,
        )
        self.assertEqual(
            repository.complete_reconciliation_calls[0][1][
                "order-2"
            ],
            TrackedOrderStatus.FILLED,
        )

    def test_reconcile_validates_notional_replacement_remainder(
        self,
    ) -> None:
        base_group = _notional_record()
        group = OrderGroupRecord(
            registration=base_group.registration,
            status=OrderGroupStatus.FAILED,
            revision=2,
            reprice_count=0,
            live_order_ids=(),
        )
        replacement_quantity = (
            Decimal("4") / Decimal("0.999")
        )
        candidate = ReconciliationCandidate(
            group=group,
            orders=(
                RecoveryOrderRecord(
                    order_id="order-1",
                    generation=0,
                    status=TrackedOrderStatus.CANCELLED,
                    quantity=None,
                ),
                RecoveryOrderRecord(
                    order_id="order-2",
                    generation=1,
                    status=TrackedOrderStatus.UNKNOWN,
                    quantity=replacement_quantity,
                ),
            ),
            interrupted_event_id="tick-event-1",
            interrupted_event_status=(
                SupervisionEventStatus.FAILED
            ),
            interrupted_claimed_revision=1,
        )
        repository = _Repository(
            reconciliation_candidates=(candidate,)
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("10"),
                            matched=Decimal("2"),
                            limit_price=Decimal("0.5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.OPEN,
                            original=replacement_quantity,
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.REPLACED,
        )
        self.assertEqual(
            repository.complete_reconciliation_calls[0][1][
                "order-2"
            ],
            TrackedOrderStatus.LIVE,
        )

    def test_reconcile_quarantines_missing_replacement_id(
        self,
    ) -> None:
        repository = _Repository(
            reconciliation_candidates=(
                _reconciliation_candidate(
                    include_replacement=False
                ),
            )
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=("order-1",),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.FAILED,
        )
        self.assertIn(
            "duplicate_replacement_cannot_be_excluded",
            results[0].error,
        )
        self.assertTrue(
            repository.fail_reconciliation_calls[0][4]
        )
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])

    def test_reconcile_quarantines_overlapping_source_and_replacement(
        self,
    ) -> None:
        repository = _Repository(
            reconciliation_candidates=(
                _reconciliation_candidate(
                    source_status=TrackedOrderStatus.LIVE
                ),
            )
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.OPEN,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.OPEN,
                            original=Decimal("20"),
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.FAILED,
        )
        self.assertTrue(
            repository.fail_reconciliation_calls[0][4]
        )
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])

    def test_reconcile_retries_unknown_remote_state_without_quarantine(
        self,
    ) -> None:
        repository = _Repository(
            reconciliation_candidates=(
                _reconciliation_candidate(),
            )
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.UNKNOWN,
                            original=Decimal("20"),
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.FAILED,
        )
        self.assertFalse(
            repository.fail_reconciliation_calls[0][4]
        )

    def test_reconcile_quarantines_replacement_size_mismatch(
        self,
    ) -> None:
        repository = _Repository(
            reconciliation_candidates=(
                _reconciliation_candidate(),
            )
        )
        gateway = _Gateway(
            inspections=(
                OrderInspectionResult(
                    requested_order_ids=(
                        "order-1",
                        "order-2",
                    ),
                    snapshots=(
                        _snapshot(
                            "order-1",
                            state=RemoteOrderState.CANCELLED,
                            original=Decimal("25"),
                            matched=Decimal("5"),
                        ),
                        _snapshot(
                            "order-2",
                            state=RemoteOrderState.OPEN,
                            original=Decimal("19"),
                            limit_price=Decimal("0.999"),
                        ),
                    ),
                ),
            ),
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        results = supervisor.reconcile()

        self.assertEqual(
            results[0].status,
            SupervisionStatus.FAILED,
        )
        self.assertIn("quantity", results[0].error)
        self.assertTrue(
            repository.fail_reconciliation_calls[0][4]
        )
        self.assertEqual(gateway.place_calls, [])

    def test_reconcile_load_failure_is_sanitized(self) -> None:
        repository = _Repository()
        repository.load_reconciliation_error = RuntimeError(
            "database unavailable"
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=_Gateway(),
        )

        with self.assertRaisesRegex(
            OrderSupervisorError,
            "database unavailable",
        ):
            supervisor.reconcile()

    def test_close_is_idempotent_and_disables_supervisor(self) -> None:
        repository = _Repository()
        gateway = _Gateway()
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
        )

        supervisor.close()
        supervisor.close()

        self.assertEqual(repository.close_calls, 1)
        self.assertEqual(gateway.close_calls, 1)
        with self.assertRaisesRegex(
            OrderSupervisorError,
            "closed",
        ):
            supervisor.reconcile()


if __name__ == "__main__":
    unittest.main()
