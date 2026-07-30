from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.domain import (
    ExecutionHandle,
    ExecutionStatus,
    OrderExecutionResult,
    OrderSide,
    OrderTemplate,
    Outcome,
    PlacedOrder,
    RepriceOnTickChange,
    ResolutionSignal,
    SignalEvidence,
)
from cbr_trading.execution import (
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
    SupervisionResult,
    SupervisionStatus,
    TickSizeChange,
)


class ResolutionSignalTests(unittest.TestCase):
    def test_normalizes_times_and_copies_attributes(self) -> None:
        attributes = {"bank": "CBR"}
        signal = ResolutionSignal(
            signal_id=" cbr:2026-07-24 ",
            source=" cbr ",
            subject=" central_bank:CBR:key_rate ",
            metric=" rate_change_bps ",
            value=Decimal("-100"),
            previous_value=Decimal("20"),
            unit=" bps ",
            direction=" cut ",
            confidence=Decimal("0.95"),
            detected_at=datetime(
                2026,
                7,
                24,
                15,
                0,
                tzinfo=timezone(timedelta(hours=2)),
            ),
            published_at=datetime(
                2026,
                7,
                24,
                13,
                0,
                tzinfo=timezone.utc,
            ),
            evidence=(
                SignalEvidence(
                    source_url=" https://example.test/release ",
                    title=" Decision ",
                ),
            ),
            attributes=attributes,
        )

        attributes["bank"] = "changed"

        self.assertEqual(signal.signal_id, "cbr:2026-07-24")
        self.assertEqual(signal.source, "cbr")
        self.assertEqual(signal.detected_at.tzinfo, timezone.utc)
        self.assertEqual(signal.detected_at.hour, 13)
        self.assertEqual(signal.attributes["bank"], "CBR")
        self.assertEqual(signal.evidence[0].title, "Decision")
        with self.assertRaises(TypeError):
            signal.attributes["bank"] = "mutated"  # type: ignore[index]

    def test_rejects_naive_time_invalid_confidence_and_float_value(self) -> None:
        common = {
            "signal_id": "signal-1",
            "source": "source",
            "subject": "subject",
            "metric": "metric",
            "value": Decimal("1"),
            "detected_at": datetime(2026, 7, 24, 13, 0),
        }
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ResolutionSignal(**common)

        common["detected_at"] = datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            ResolutionSignal(**common, confidence=Decimal("1.1"))
        with self.assertRaisesRegex(TypeError, "Decimal, str, or bool"):
            ResolutionSignal(**{**common, "value": 1.5})
        with self.assertRaisesRegex(TypeError, "previous_value"):
            ResolutionSignal(**common, previous_value=1.5)


class OrderIntentTests(unittest.TestCase):
    def test_template_binds_to_stable_intent_with_tick_policy(self) -> None:
        policy = RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        )
        template = OrderTemplate(
            template_id="rule-17:YES",
            strategy_id="rate-decision",
            account_name="primary",
            condition_id="condition-1",
            outcome=Outcome.YES,
            side=OrderSide.BUY,
            desired_price=Decimal("0.999"),
            notional=Decimal("100"),
            lifecycle_policy=policy,
            metadata={"rule_id": 17},
        )

        intent = template.bind(signal_id="cbr:2026-07-24")

        self.assertEqual(intent.intent_id, "cbr:2026-07-24/rule-17:YES")
        self.assertEqual(intent.signal_id, "cbr:2026-07-24")
        self.assertEqual(intent.notional, Decimal("100"))
        self.assertIsNone(intent.quantity)
        self.assertEqual(intent.lifecycle_policy.cancel_scope, "order_group")
        self.assertEqual(intent.lifecycle_policy.max_reprices, 1)
        self.assertTrue(intent.lifecycle_policy.submit_first)

    def test_requires_exactly_one_positive_sizing_mode(self) -> None:
        base = {
            "template_id": "template",
            "strategy_id": "strategy",
            "account_name": "account",
            "condition_id": "condition",
            "outcome": Outcome.YES,
            "side": OrderSide.BUY,
            "desired_price": Decimal("0.99"),
        }

        with self.assertRaisesRegex(ValueError, "exactly one"):
            OrderTemplate(**base)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            OrderTemplate(
                **base,
                quantity=Decimal("10"),
                notional=Decimal("10"),
            )
        with self.assertRaisesRegex(ValueError, "quantity must be positive"):
            OrderTemplate(**base, quantity=Decimal("0"))

    def test_reprice_policy_requires_a_finer_tick(self) -> None:
        with self.assertRaisesRegex(ValueError, "finer"):
            RepriceOnTickChange(
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.01"),
            )
        with self.assertRaisesRegex(TypeError, "submit_first"):
            RepriceOnTickChange(
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.001"),
                submit_first="false",
            )


class ExecutionContractTests(unittest.TestCase):
    def _intent(self):
        return OrderTemplate(
            template_id="rule-17:YES",
            strategy_id="rate-decision",
            account_name="primary",
            condition_id="condition-1",
            outcome=Outcome.YES,
            side=OrderSide.BUY,
            desired_price=Decimal("0.999"),
            quantity=Decimal("25"),
        ).bind(signal_id="signal-1")

    def test_submitted_result_owns_exact_live_orders(self) -> None:
        intent = self._intent()
        order = PlacedOrder(
            order_id="order-1",
            asset_id="asset-yes",
            effective_price=Decimal("0.99"),
            quantity=Decimal("25"),
        )
        handle = ExecutionHandle(
            order_group_id="group-1",
            intent_id=intent.intent_id,
            account_name=intent.account_name,
            condition_id=intent.condition_id,
            outcome=intent.outcome,
            asset_id=order.asset_id,
            live_order_ids=(order.order_id,),
        )

        result = OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.SUBMITTED,
            attempted=True,
            orders=(order,),
            handle=handle,
        )

        self.assertEqual(result.handle.order_group_id, "group-1")
        self.assertEqual(result.handle.live_order_ids, ("order-1",))

    def test_submitted_result_rejects_unowned_order_reference(self) -> None:
        intent = self._intent()
        order = PlacedOrder(
            order_id="order-1",
            asset_id="asset-yes",
            effective_price=Decimal("0.99"),
            quantity=Decimal("25"),
        )
        handle = ExecutionHandle(
            order_group_id="group-1",
            intent_id=intent.intent_id,
            account_name=intent.account_name,
            condition_id=intent.condition_id,
            outcome=intent.outcome,
            asset_id=order.asset_id,
            live_order_ids=("another-order",),
        )

        with self.assertRaisesRegex(ValueError, "absent from result"):
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.SUBMITTED,
                attempted=True,
                orders=(order,),
                handle=handle,
            )

    def test_submitted_result_rejects_another_asset(self) -> None:
        intent = self._intent()
        order = PlacedOrder(
            order_id="order-1",
            asset_id="another-asset",
            effective_price=Decimal("0.99"),
            quantity=Decimal("25"),
        )
        handle = ExecutionHandle(
            order_group_id="group-1",
            intent_id=intent.intent_id,
            account_name=intent.account_name,
            condition_id=intent.condition_id,
            outcome=intent.outcome,
            asset_id="asset-yes",
            live_order_ids=(order.order_id,),
        )

        with self.assertRaisesRegex(ValueError, "another asset"):
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.SUBMITTED,
                attempted=True,
                orders=(order,),
                handle=handle,
            )

    def test_preparation_summary_requires_unique_templates(self) -> None:
        ready = PreparationItem(
            template_id="template-1",
            status=PreparationStatus.READY,
            prepared_key="prepared-1",
        )
        self.assertTrue(PreparationSummary(items=(ready,)).ready)

        with self.assertRaisesRegex(ValueError, "duplicate"):
            PreparationSummary(items=(ready, ready))

    def test_tick_event_and_supervision_result_are_source_neutral(self) -> None:
        event = TickSizeChange(
            event_id="tick-event-1",
            asset_id="asset-yes",
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            observed_at=datetime(
                2026,
                7,
                24,
                15,
                0,
                tzinfo=timezone(timedelta(hours=2)),
            ),
        )
        result = SupervisionResult(
            event_id=event.event_id,
            order_group_id="group-1",
            status=SupervisionStatus.REPLACED,
            cancelled_order_ids=("order-1",),
            replacement_order_ids=("order-2",),
        )

        self.assertEqual(event.observed_at.hour, 13)
        self.assertEqual(result.cancelled_order_ids, ("order-1",))
        self.assertEqual(result.replacement_order_ids, ("order-2",))


if __name__ == "__main__":
    unittest.main()
