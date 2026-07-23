from __future__ import annotations

import unittest

from cbr_trading.client import DiscoveryResult
from cbr_trading.pipeline import (
    DryRunOrderExecutor,
    OrderExecutionResult,
    OrderIntent,
    PipelineOutcome,
    TradingPipeline,
)
from cbr_trading.settings import CbrSettings


def _release(rate: float = 14.25) -> DiscoveryResult:
    return DiscoveryResult(
        ok=True,
        reason="published",
        url=(
            "https://www.cbr.ru/eng/press/pr/"
            "?file=19062026_133000key_e.htm"
        ),
        request_url="https://www.cbr.ru/release?_ts=1",
        status_code=200,
        content_type="text/html",
        title=(
            "Bank of Russia cuts the key rate by 25 bp "
            f"to {rate}% p.a."
        ),
        new_rate=rate,
    )


def _subscription(
    *,
    rule_id: int = 1,
    threshold: float = -10,
    operator: str = "<=",
) -> dict:
    return {
        "id": rule_id,
        "rule_key": f"cbr_rule_{rule_id}",
        "account_name": "main",
        "condition_id": f"condition-{rule_id}",
        "order_qty": 100,
        "order_price": 0.51,
        "params": {
            "threshold": threshold,
            "cmp": operator,
            "decision_mode": "binary_yes_no",
        },
    }


class SpyExecutor:
    def __init__(self, trace: list[str]):
        self.trace = trace

    def execute(
        self,
        intents: list[OrderIntent],
        *,
        release: DiscoveryResult,
    ) -> list[OrderExecutionResult]:
        self.trace.append("executor_started")
        results = DryRunOrderExecutor().execute(
            intents,
            release=release,
        )
        self.trace.append("executor_finished")
        return results


class FailingExecutor:
    def __init__(self, trace: list[str]):
        self.trace = trace

    def execute(
        self,
        intents: list[OrderIntent],
        *,
        release: DiscoveryResult,
    ) -> list[OrderExecutionResult]:
        self.trace.append("order_attempt")
        raise RuntimeError("CLOB unavailable")


class PipelineTests(unittest.TestCase):
    def test_calculates_change_and_builds_dry_run_orders(self) -> None:
        pipeline = TradingPipeline(executor=DryRunOrderExecutor())

        outcome = pipeline.process(
            release=_release(),
            previous_rate=14.5,
            subscriptions=[
                _subscription(rule_id=1, threshold=-10),
                _subscription(rule_id=2, threshold=-50),
            ],
        )

        self.assertEqual(outcome.change_bps, -25)
        self.assertEqual(outcome.direction, "decrease")
        self.assertEqual(len(outcome.evaluations), 2)
        self.assertEqual(len(outcome.order_results), 2)
        self.assertEqual(
            [result.status for result in outcome.order_results],
            ["DRY_RUN", "DRY_RUN"],
        )
        self.assertTrue(
            all(
                not result.attempted
                for result in outcome.order_results
            )
        )

    def test_notifier_runs_only_after_executor_finishes(self) -> None:
        trace: list[str] = []
        pipeline = TradingPipeline(
            executor=SpyExecutor(trace),
            notifier=lambda outcome: trace.append("telegram"),
        )

        pipeline.process(
            release=_release(),
            previous_rate=14.5,
            subscriptions=[_subscription()],
        )

        self.assertEqual(
            trace,
            ["executor_started", "executor_finished", "telegram"],
        )

    def test_executor_failure_is_reported_before_notification(self) -> None:
        trace: list[str] = []
        observed: list[PipelineOutcome] = []

        def notify(outcome: PipelineOutcome) -> None:
            trace.append("telegram")
            observed.append(outcome)

        pipeline = TradingPipeline(
            executor=FailingExecutor(trace),
            notifier=notify,
        )
        outcome = pipeline.process(
            release=_release(),
            previous_rate=14.5,
            subscriptions=[_subscription()],
        )

        self.assertEqual(trace, ["order_attempt", "telegram"])
        self.assertIn("CLOB unavailable", outcome.execution_error or "")
        self.assertIs(outcome, observed[0])

    def test_missing_previous_rate_skips_rules_but_still_notifies(
        self,
    ) -> None:
        trace: list[str] = []
        pipeline = TradingPipeline(
            executor=SpyExecutor(trace),
            notifier=lambda outcome: trace.append("telegram"),
        )

        outcome = pipeline.process(
            release=_release(),
            previous_rate=None,
            subscriptions=[_subscription()],
        )

        self.assertIsNone(outcome.change_bps)
        self.assertEqual(outcome.evaluations, ())
        self.assertEqual(outcome.order_results, ())
        self.assertEqual(
            trace,
            ["executor_started", "executor_finished", "telegram"],
        )

    def test_invalid_order_config_is_skipped(self) -> None:
        subscription = _subscription()
        subscription["account_name"] = ""
        subscription["order_price"] = 1.2
        pipeline = TradingPipeline(executor=DryRunOrderExecutor())

        outcome = pipeline.process(
            release=_release(),
            previous_rate=14.5,
            subscriptions=[subscription],
        )

        result = outcome.order_results[0]
        self.assertEqual(result.status, "SKIPPED")
        self.assertFalse(result.attempted)
        self.assertIn("missing_account_name", result.error or "")
        self.assertIn("invalid_order_price", result.error or "")

    def test_previous_rate_is_loaded_from_environment(self) -> None:
        settings = CbrSettings.from_env({"BOR_PREV_RATE": "14.5"})
        self.assertEqual(settings.previous_rate, 14.5)


if __name__ == "__main__":
    unittest.main()
