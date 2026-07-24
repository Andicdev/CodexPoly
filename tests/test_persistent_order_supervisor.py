from __future__ import annotations

import unittest
from datetime import datetime, timezone
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
    RemoteOrderSnapshot,
    RemoteOrderState,
    SupervisionClaim,
    SupervisionStatus,
    TickSizeChange,
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
) -> OrderGroupRecord:
    return OrderGroupRecord(
        registration=registration_from_handle(
            _handle(live_order_ids=live_order_ids),
            policy=_policy(),
        ),
        status=OrderGroupStatus.ACTIVE,
        revision=0,
        reprice_count=0,
        live_order_ids=live_order_ids,
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


class _Repository:
    def __init__(
        self,
        *,
        groups=(),
        claim: SupervisionClaim | None = None,
    ):
        self.groups = tuple(groups)
        self.claim = claim or SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )
        self.register_calls = []
        self.load_calls = []
        self.claim_calls = []
        self.complete_calls = []
        self.complete_without_calls = []
        self.fail_calls = []
        self.close_calls = 0
        self.complete_error: Exception | None = None

    def register(self, handle, *, policy, metadata=None):
        self.register_calls.append((handle, policy, metadata))
        return _record(live_order_ids=handle.live_order_ids)

    def load_active_for_asset(self, asset_id):
        self.load_calls.append(asset_id)
        return self.groups

    def claim_tick_size_change(self, *, order_group_id, event):
        self.claim_calls.append((order_group_id, event))
        return self.claim

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
        self.close_calls = 0

    def inspect_orders(self, *, account_name, order_ids):
        normalized = tuple(order_ids)
        self.inspect_calls.append((account_name, normalized))
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
        return self.cancellation

    def place_replacement(self, request):
        self.place_calls.append(request)
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
            tuple(
                observation.phase
                for observation
                in repository.complete_calls[0][4]
            ),
            (
                OrderObservationPhase.PRE_CANCEL,
                OrderObservationPhase.POST_CANCEL,
            ),
        )
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

    def test_partial_cancel_fails_without_placing_replacement(self) -> None:
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
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(
            repository.fail_calls[0][2],
            ("order-1",),
        )
        self.assertEqual(repository.fail_calls[0][3], ())

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
            repository.fail_calls[0][3],
            (replacement,),
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
        self.assertEqual(gateway.place_calls, [])
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

    def test_partial_fill_replaces_only_final_remaining_quantity(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        replacement = _replacement(quantity=Decimal("18"))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                    original=Decimal("25"),
                    matched=Decimal("5"),
                ),
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.CANCELLED,
                    original=Decimal("25"),
                    matched=Decimal("7"),
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
            Decimal("18"),
        )
        self.assertEqual(
            repository.complete_calls[0][2],
            (replacement,),
        )

    def test_fill_during_cancel_completes_without_replacement(
        self,
    ) -> None:
        repository = _Repository(groups=(_record(),))
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                    original=Decimal("25"),
                    matched=Decimal("5"),
                ),
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
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(repository.complete_calls, [])
        self.assertEqual(
            repository.complete_without_calls[0][1],
            ("order-1",),
        )

    def test_notional_sizing_replaces_only_unfilled_old_notional(
        self,
    ) -> None:
        repository = _Repository(groups=(_notional_record(),))
        remaining_notional = Decimal("4")
        replacement_quantity = (
            remaining_notional / Decimal("0.999")
        )
        replacement = _replacement(
            quantity=replacement_quantity
        )
        gateway = _Gateway(
            inspections=(
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.OPEN,
                    original=Decimal("10"),
                    matched=Decimal("1"),
                    limit_price=Decimal("0.50"),
                ),
                _inspection(
                    ("order-1",),
                    state=RemoteOrderState.CANCELLED,
                    original=Decimal("10"),
                    matched=Decimal("2"),
                    limit_price=Decimal("0.50"),
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
        request = gateway.place_calls[0]
        self.assertIsNone(request.quantity)
        self.assertEqual(request.notional, remaining_notional)
        self.assertEqual(
            repository.complete_calls[0][2],
            (replacement,),
        )

    def test_already_filled_order_needs_no_cancellation(
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
            SupervisionStatus.COMPLETED,
        )
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])

    def test_unconfirmed_post_cancel_state_blocks_replacement(
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

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertIn("not terminal", results[0].error)
        self.assertEqual(gateway.place_calls, [])

    def test_failed_post_cancel_lookup_blocks_replacement(
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

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertIn("lookup unavailable", results[0].error)
        self.assertEqual(gateway.place_calls, [])
        self.assertEqual(
            repository.fail_calls[0][2],
            ("order-1",),
        )

    def test_remote_quantity_mismatch_blocks_cancellation(self) -> None:
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

        self.assertEqual(results[0].status, SupervisionStatus.FAILED)
        self.assertIn("quantity does not match", results[0].error)
        self.assertEqual(gateway.cancel_calls, [])
        self.assertEqual(gateway.place_calls, [])

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
