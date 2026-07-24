from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.client import DiscoveryResult
from cbr_trading.domain import Outcome, RepriceOnTickChange, ResolutionSignal
from cbr_trading.pipeline import build_order_intent
from cbr_trading.sources.cbr import (
    CBR_KEY_RATE_SUBJECT,
    CBR_KEY_RATE_TARGET_METRIC,
    CbrResolutionSource,
    resolution_signal_from_discovery,
)
from cbr_trading.strategies.cbr_rate_decision import (
    CbrRateDecisionStrategy,
    CbrStrategyConfigurationError,
)
from cbr_trading.trading_rules import evaluate_rule


def _discovery(*, ok: bool = True, rate: float | None = 14.25) -> DiscoveryResult:
    return DiscoveryResult(
        ok=ok,
        reason="published" if ok else "not_published_yet",
        url="https://www.cbr.ru/eng/press/pr/?file=release",
        request_url=(
            "https://www.cbr.ru/eng/press/pr/"
            "?file=release&_ts=first"
        ),
        status_code=200 if ok else 404,
        content_type="text/html",
        title="Bank of Russia cuts the key rate to 14.25% p.a." if ok else "",
        new_rate=rate,
        raw_preview="Bank of Russia cuts the key rate to 14.25% p.a.",
        published_at="2026-07-24T13:30:00Z",
    )


def _subscription() -> dict:
    return {
        "id": 17,
        "rule_key": "cbr_cut",
        "account_name": "primary",
        "condition_id": "condition-17",
        "order_qty": 100,
        "order_price": 0.51,
        "params": {
            "threshold": -10,
            "cmp": "<=",
            "decision_mode": "binary_yes_no",
            "order_price_yes": 0.999,
            "order_price_no": 0.95,
            "order_lifecycle": {
                "kind": "reprice_on_tick_change",
                "old_tick": "0.01",
                "new_tick": "0.001",
            },
        },
    }


def _signal(*, previous_rate: Decimal | None = Decimal("14.5")):
    return resolution_signal_from_discovery(
        _discovery(),
        previous_rate=previous_rate,
        detected_at=datetime(2026, 7, 24, 13, 30, 1, tzinfo=timezone.utc),
    )


class _DiscoveryClient:
    def __init__(self, result: DiscoveryResult):
        self.result = result
        self.calls = 0

    def run_once(self) -> DiscoveryResult:
        self.calls += 1
        return self.result


class CbrSourceAdapterTests(unittest.TestCase):
    def test_emits_source_neutral_signal_with_stable_id(self) -> None:
        first = _signal()
        second = resolution_signal_from_discovery(
            replace(
                _discovery(),
                request_url=(
                    "https://www.cbr.ru/eng/press/pr/"
                    "?file=release&_ts=second"
                ),
            ),
            previous_rate=Decimal("14.5"),
            detected_at=datetime(2026, 7, 24, 13, 30, 2, tzinfo=timezone.utc),
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(first.signal_id, second.signal_id)
        self.assertEqual(first.subject, CBR_KEY_RATE_SUBJECT)
        self.assertEqual(first.metric, CBR_KEY_RATE_TARGET_METRIC)
        self.assertEqual(first.value, Decimal("14.25"))
        self.assertEqual(first.previous_value, Decimal("14.5"))
        self.assertEqual(first.direction, "decrease")
        self.assertEqual(first.published_at.hour, 13)
        self.assertEqual(
            first.evidence[0].source_url,
            "https://www.cbr.ru/eng/press/pr/?file=release",
        )

    def test_source_does_not_load_previous_rate_before_publication(self) -> None:
        client = _DiscoveryClient(_discovery(ok=False, rate=None))

        def forbidden_provider() -> Decimal:
            raise AssertionError("previous rate must not be loaded")

        source = CbrResolutionSource(
            client,
            previous_rate_provider=forbidden_provider,
            clock=lambda: datetime.now(timezone.utc),
        )

        self.assertEqual(source.poll_once(), ())
        self.assertEqual(client.calls, 1)

    def test_published_discovery_requires_canonical_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical URL"):
            resolution_signal_from_discovery(
                replace(_discovery(), url=""),
                previous_rate=Decimal("14.5"),
                detected_at=datetime.now(timezone.utc),
            )


class CbrStrategyAdapterTests(unittest.TestCase):
    def test_prepares_both_outcomes_and_selects_existing_rule_decision(self) -> None:
        subscription = _subscription()
        strategy = CbrRateDecisionStrategy([subscription])

        templates = strategy.order_templates()
        decision = strategy.evaluate_decision(_signal())

        self.assertEqual([item.outcome for item in templates], [Outcome.YES, Outcome.NO])
        self.assertEqual(
            [item.desired_price for item in templates],
            [Decimal("0.999"), Decimal("0.95")],
        )
        self.assertTrue(
            all(
                isinstance(item.lifecycle_policy, RepriceOnTickChange)
                for item in templates
            )
        )
        self.assertEqual(decision.change_bps, Decimal("-25.0"))
        self.assertEqual(decision.direction, "decrease")
        self.assertEqual(len(decision.intents), 1)

        intent = decision.intents[0]
        self.assertEqual(intent.outcome, Outcome.YES)
        self.assertEqual(intent.desired_price, Decimal("0.999"))
        self.assertEqual(intent.quantity, Decimal("100"))
        self.assertEqual(
            intent.intent_id,
            f"{_signal().signal_id}/cbr-rule:17:YES",
        )

    def test_new_intent_preserves_legacy_order_decision_fields(self) -> None:
        subscription = _subscription()
        signal = _signal()
        assert signal is not None
        evaluation = evaluate_rule(-25.0, subscription)
        legacy = build_order_intent(evaluation, subscription)
        modern = CbrRateDecisionStrategy([subscription]).evaluate(signal)[0]

        self.assertEqual(modern.account_name, legacy.account_name)
        self.assertEqual(modern.condition_id, legacy.condition_id)
        self.assertEqual(modern.outcome.value, legacy.action)
        self.assertEqual(modern.quantity, Decimal(str(legacy.quantity)))
        self.assertEqual(
            modern.desired_price,
            Decimal(str(legacy.limit_price)),
        )

    def test_missing_previous_rate_is_accepted_but_not_traded(self) -> None:
        signal = _signal(previous_rate=None)
        assert signal is not None
        decision = CbrRateDecisionStrategy(
            [_subscription()]
        ).evaluate_decision(signal)

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "previous_rate_unavailable")
        self.assertEqual(decision.intents, ())

    def test_unsupported_signal_is_ignored(self) -> None:
        signal = _signal()
        assert signal is not None
        unrelated = ResolutionSignal(
            signal_id="other:1",
            source="sec",
            subject="company:example",
            metric="earnings.eps",
            value=Decimal("1.25"),
            detected_at=signal.detected_at,
        )
        decision = CbrRateDecisionStrategy(
            [_subscription()]
        ).evaluate_decision(unrelated)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "unsupported_signal")
        self.assertEqual(decision.intents, ())

    def test_non_numeric_cbr_signal_is_rejected(self) -> None:
        signal = _signal()
        assert signal is not None
        invalid = ResolutionSignal(
            signal_id=signal.signal_id,
            source=signal.source,
            subject=signal.subject,
            metric=signal.metric,
            value="not-a-rate",
            previous_value=signal.previous_value,
            detected_at=signal.detected_at,
        )
        decision = CbrRateDecisionStrategy(
            [_subscription()]
        ).evaluate_decision(invalid)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "invalid_signal_value")

    def test_invalid_rule_fails_during_preparation(self) -> None:
        subscription = _subscription()
        subscription["account_name"] = ""

        with self.assertRaisesRegex(
            CbrStrategyConfigurationError,
            "invalid CBR rule",
        ):
            CbrRateDecisionStrategy([subscription])


if __name__ == "__main__":
    unittest.main()
