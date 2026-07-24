from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import ExecutionStatus
from cbr_trading.execution import (
    CbrWarmPreparedExecutorAdapter,
    PreparationStatus,
    cbr_preparation_context,
)
from cbr_trading.live.runner_executor import (
    LivePreparationSummary,
    LivePreparedOrderSummary,
)
from cbr_trading.pipeline import (
    OrderExecutionResult as LegacyOrderExecutionResult,
)
from cbr_trading.sources.cbr import resolution_signal_from_discovery
from cbr_trading.strategies.cbr_rate_decision import CbrRateDecisionStrategy
from tests.test_cbr_contract_adapters import _discovery, _subscription


class _LegacyWarmExecutor:
    def __init__(
        self,
        *,
        preparation_error: Exception | None = None,
        result_mode: str = "success",
        omit_prepared_details: bool = False,
        initial_tick_size: Decimal | None = None,
    ):
        self.preparation_error = preparation_error
        self.result_mode = result_mode
        self.omit_prepared_details = omit_prepared_details
        self.initial_tick_size = initial_tick_size
        self.prepare_calls: list[dict] = []
        self.execute_calls: list[dict] = []
        self.closed = False

    def prepare(
        self,
        *,
        release_url: str,
        reserve_claims: bool = True,
    ) -> LivePreparationSummary:
        self.prepare_calls.append(
            {
                "release_url": release_url,
                "reserve_claims": reserve_claims,
            }
        )
        if self.preparation_error is not None:
            raise self.preparation_error
        yes_limit_price = (
            Decimal("0.99")
            if self.initial_tick_size == Decimal("0.01")
            else Decimal("0.999")
        )
        prepared_orders = () if self.omit_prepared_details else (
            LivePreparedOrderSummary(
                rule_id=17,
                rule_key="cbr_cut",
                account_name="primary",
                condition_id="condition-17",
                outcome="YES",
                token_id="asset-yes",
                quantity=Decimal("100"),
                limit_price=yes_limit_price,
                desired_price=(
                    Decimal("0.999")
                    if self.initial_tick_size is not None
                    else None
                ),
                tick_size=self.initial_tick_size,
            ),
            LivePreparedOrderSummary(
                rule_id=17,
                rule_key="cbr_cut",
                account_name="primary",
                condition_id="condition-17",
                outcome="NO",
                token_id="asset-no",
                quantity=Decimal("100"),
                limit_price=Decimal("0.95"),
                desired_price=(
                    Decimal("0.95")
                    if self.initial_tick_size is not None
                    else None
                ),
                tick_size=self.initial_tick_size,
            ),
        )
        return LivePreparationSummary(
            rule_count=1,
            account_count=1,
            outcome_count=2,
            maximum_notional=Decimal("99.9"),
            prepared_orders=prepared_orders,
        )

    def execute(self, intents, *, release):
        intents = tuple(intents)
        self.execute_calls.append(
            {
                "intents": intents,
                "release": release,
            }
        )
        if self.result_mode == "rejected":
            return tuple(
                LegacyOrderExecutionResult(
                    intent=intent,
                    status="REJECTED",
                    attempted=True,
                    success=False,
                    error="order rejected",
                )
                for intent in intents
            )
        if self.result_mode == "ambiguous":
            return tuple(
                LegacyOrderExecutionResult(
                    intent=intent,
                    status="AMBIGUOUS",
                    attempted=True,
                    success=None,
                    error="timeout",
                )
                for intent in intents
            )
        if self.result_mode == "extra_result":
            return tuple(
                LegacyOrderExecutionResult(
                    intent=intent,
                    status="LIVE",
                    attempted=True,
                    success=True,
                    order_id=f"order-{intent.action.lower()}",
                )
                for intent in (*intents, intents[0])
            )
        return tuple(
            LegacyOrderExecutionResult(
                intent=intent,
                status="LIVE",
                attempted=True,
                success=True,
                order_id=f"order-{intent.action.lower()}",
            )
            for intent in intents
        )

    def close(self) -> None:
        self.closed = True


def _setup():
    release = _discovery()
    signal = resolution_signal_from_discovery(
        release,
        previous_rate=Decimal("14.5"),
        detected_at=datetime(2026, 7, 24, 13, 30, 1, tzinfo=timezone.utc),
    )
    assert signal is not None
    strategy = CbrRateDecisionStrategy([_subscription()])
    context = cbr_preparation_context(release.url)
    return signal, strategy, context


class CbrPreparedExecutorAdapterTests(unittest.TestCase):
    def test_prepares_all_templates_and_maps_success_to_owned_group(self) -> None:
        signal, strategy, context = _setup()
        legacy = _LegacyWarmExecutor()
        adapter = CbrWarmPreparedExecutorAdapter(legacy)

        summary = adapter.prepare(
            strategy.order_templates(),
            context=context,
        )
        intents = strategy.evaluate(signal)
        results = adapter.execute(intents, signal=signal)

        self.assertTrue(summary.ready)
        self.assertEqual(summary.context, context)
        self.assertEqual(
            [item.status for item in summary.items],
            [PreparationStatus.READY, PreparationStatus.READY],
        )
        self.assertEqual(
            legacy.prepare_calls,
            [{"release_url": release_url(), "reserve_claims": True}],
        )
        self.assertEqual(len(legacy.execute_calls), 1)
        self.assertEqual(
            legacy.execute_calls[0]["intents"][0].action,
            "YES",
        )
        self.assertEqual(
            legacy.execute_calls[0]["release"].url,
            release_url(),
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.status, ExecutionStatus.SUBMITTED)
        self.assertTrue(result.attempted)
        self.assertEqual(result.orders[0].asset_id, "asset-yes")
        self.assertEqual(result.orders[0].effective_price, Decimal("0.999"))
        self.assertEqual(result.handle.live_order_ids, ("order-yes",))
        self.assertEqual(result.handle.signal_id, signal.signal_id)
        self.assertEqual(
            result.handle.template_id,
            intents[0].template_id,
        )
        self.assertEqual(result.handle.side, intents[0].side)
        self.assertEqual(
            result.handle.desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(result.handle.quantity, Decimal("100"))
        self.assertTrue(
            result.handle.order_group_id.startswith("order-group:")
        )

    def test_scope_mismatch_does_not_consume_prepared_executor(self) -> None:
        signal, strategy, context = _setup()
        legacy = _LegacyWarmExecutor()
        adapter = CbrWarmPreparedExecutorAdapter(legacy)
        adapter.prepare(strategy.order_templates(), context=context)
        intents = strategy.evaluate(signal)
        wrong_signal = replace(signal, signal_id="cbr:key_rate:wrong")

        rejected = adapter.execute(intents, signal=wrong_signal)
        accepted = adapter.execute(intents, signal=signal)

        self.assertEqual(
            rejected[0].error,
            "prepared_signal_scope_mismatch",
        )
        self.assertFalse(rejected[0].attempted)
        self.assertEqual(accepted[0].status, ExecutionStatus.SUBMITTED)
        self.assertEqual(len(legacy.execute_calls), 1)

    def test_executes_effective_old_tick_price_but_keeps_desired_price(
        self,
    ) -> None:
        signal, strategy, context = _setup()
        legacy = _LegacyWarmExecutor(
            initial_tick_size=Decimal("0.01")
        )
        adapter = CbrWarmPreparedExecutorAdapter(legacy)

        summary = adapter.prepare(
            strategy.order_templates(),
            context=context,
        )
        result = adapter.execute(
            strategy.evaluate(signal),
            signal=signal,
        )[0]

        self.assertTrue(summary.ready)
        sent_intent = legacy.execute_calls[0]["intents"][0]
        self.assertEqual(sent_intent.limit_price, Decimal("0.99"))
        self.assertEqual(
            result.orders[0].effective_price,
            Decimal("0.99"),
        )
        self.assertEqual(
            result.handle.desired_price,
            Decimal("0.999"),
        )

    def test_empty_selection_consumes_executor_and_expires_legacy_claims(self) -> None:
        signal, strategy, context = _setup()
        legacy = _LegacyWarmExecutor()
        adapter = CbrWarmPreparedExecutorAdapter(legacy)
        adapter.prepare(strategy.order_templates(), context=context)

        self.assertEqual(adapter.execute((), signal=signal), ())
        self.assertEqual(len(legacy.execute_calls), 1)
        self.assertEqual(legacy.execute_calls[0]["intents"], ())

    def test_preparation_failure_is_returned_and_sanitized(self) -> None:
        _, strategy, context = _setup()
        legacy = _LegacyWarmExecutor(
            preparation_error=RuntimeError(
                "DATABASE_URL=hidden-value"
            )
        )
        adapter = CbrWarmPreparedExecutorAdapter(legacy)

        summary = adapter.prepare(
            strategy.order_templates(),
            context=context,
        )

        self.assertFalse(summary.ready)
        self.assertTrue(
            all(
                item.status == PreparationStatus.FAILED
                for item in summary.items
            )
        )
        self.assertNotIn("hidden-value", summary.items[0].error or "")
        self.assertIn("[REDACTED]", summary.items[0].error or "")

    def test_incomplete_legacy_preparation_fails_closed(self) -> None:
        _, strategy, context = _setup()
        legacy = _LegacyWarmExecutor(omit_prepared_details=True)
        adapter = CbrWarmPreparedExecutorAdapter(legacy)

        summary = adapter.prepare(
            strategy.order_templates(),
            context=context,
        )

        self.assertFalse(summary.ready)
        self.assertIn("incomplete", summary.items[0].error or "")

    def test_rejected_and_ambiguous_legacy_results_are_preserved(self) -> None:
        signal, strategy, context = _setup()
        intents = strategy.evaluate(signal)

        rejected_adapter = CbrWarmPreparedExecutorAdapter(
            _LegacyWarmExecutor(result_mode="rejected")
        )
        rejected_adapter.prepare(
            strategy.order_templates(),
            context=context,
        )
        ambiguous_adapter = CbrWarmPreparedExecutorAdapter(
            _LegacyWarmExecutor(result_mode="ambiguous")
        )
        ambiguous_adapter.prepare(
            strategy.order_templates(),
            context=context,
        )

        rejected = rejected_adapter.execute(intents, signal=signal)
        ambiguous = ambiguous_adapter.execute(intents, signal=signal)

        self.assertEqual(rejected[0].status, ExecutionStatus.REJECTED)
        self.assertEqual(ambiguous[0].status, ExecutionStatus.AMBIGUOUS)

    def test_legacy_result_count_mismatch_is_ambiguous(self) -> None:
        signal, strategy, context = _setup()
        adapter = CbrWarmPreparedExecutorAdapter(
            _LegacyWarmExecutor(result_mode="extra_result")
        )
        adapter.prepare(strategy.order_templates(), context=context)

        results = adapter.execute(strategy.evaluate(signal), signal=signal)

        self.assertEqual(results[0].status, ExecutionStatus.AMBIGUOUS)
        self.assertEqual(
            results[0].error,
            "legacy_batch_result_count_mismatch",
        )

    def test_close_is_idempotent(self) -> None:
        legacy = _LegacyWarmExecutor()
        adapter = CbrWarmPreparedExecutorAdapter(legacy)

        adapter.close()
        adapter.close()

        self.assertTrue(legacy.closed)


def release_url() -> str:
    return "https://www.cbr.ru/eng/press/pr/?file=release"


if __name__ == "__main__":
    unittest.main()
