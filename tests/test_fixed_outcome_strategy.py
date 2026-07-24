from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import (
    KeepOpenPolicy,
    Outcome,
    ResolutionSignal,
)
from cbr_trading.sources import ManualResolutionSource
from cbr_trading.strategies import (
    FixedOutcomeConfigurationError,
    FixedOutcomeStrategy,
)


def _rule() -> dict:
    return {
        "id": 103,
        "type": "resolution_market",
        "ticker": "ANTHROPIC",
        "rule_key": "anthropic_next_opus_by_2026_07_24_yes",
        "account_name": "KinderSman",
        "condition_id": "0x" + ("7" * 64),
        "order_qty": 100,
        "order_price": 0.9,
        "params": {
            "source": "anthropic_official",
            "subject": "next_claude_opus",
            "metric": "public_release",
            "execution_path": "resolution",
            "decision_mode": "fixed_outcome",
            "signal_value": True,
            "action": "YES",
            "order_price_yes": 0.9,
            "order_lifecycle": {"kind": "keep_open"},
        },
    }


def _signal(*, value: object = True) -> ResolutionSignal:
    return ResolutionSignal(
        signal_id="manual-preflight:rule:103",
        source="anthropic_official",
        subject="next_claude_opus",
        metric="public_release",
        value=value,
        detected_at=datetime.now(timezone.utc),
    )


class FixedOutcomeStrategyTests(unittest.TestCase):
    def test_prepares_only_configured_outcome_and_binds_match(
        self,
    ) -> None:
        strategy = FixedOutcomeStrategy((_rule(),))

        templates = strategy.order_templates()
        intents = strategy.evaluate(_signal())

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].outcome, Outcome.YES)
        self.assertEqual(
            templates[0].desired_price,
            Decimal("0.9"),
        )
        self.assertEqual(templates[0].quantity, Decimal("100"))
        self.assertIsInstance(
            templates[0].lifecycle_policy,
            KeepOpenPolicy,
        )
        self.assertEqual(len(intents), 1)
        self.assertEqual(
            intents[0],
            templates[0].bind(
                signal_id="manual-preflight:rule:103"
            ),
        )

    def test_ignores_nonmatching_signal_value(self) -> None:
        strategy = FixedOutcomeStrategy((_rule(),))

        self.assertEqual(strategy.evaluate(_signal(value=False)), ())

    def test_rejects_rule_without_explicit_signal_value(
        self,
    ) -> None:
        rule = _rule()
        del rule["params"]["signal_value"]

        with self.assertRaisesRegex(
            FixedOutcomeConfigurationError,
            "signal_value",
        ):
            FixedOutcomeStrategy((rule,))


class ManualResolutionSourceTests(unittest.TestCase):
    def test_emits_controlled_signal_exactly_once(self) -> None:
        signal = _signal()
        source = ManualResolutionSource(
            source_name="anthropic_official",
            signals=(signal,),
        )

        self.assertEqual(source.poll_once(), (signal,))
        self.assertEqual(source.poll_once(), ())

    def test_rejects_signal_from_another_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            ManualResolutionSource(
                source_name="sec",
                signals=(_signal(),),
            )


if __name__ == "__main__":
    unittest.main()
