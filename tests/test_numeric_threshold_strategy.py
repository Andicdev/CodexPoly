from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import (
    OrderSide,
    OrderTemplate,
    Outcome,
    ResolutionSignal,
)
from cbr_trading.strategies import (
    NUMERIC_THRESHOLD_STRATEGY_ID,
    NumericThresholdConfigurationError,
    NumericThresholdRule,
    NumericThresholdStrategy,
)


def _template(outcome: Outcome) -> OrderTemplate:
    return OrderTemplate(
        template_id=f"nvts:{outcome.value}",
        strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
        account_name="primary",
        condition_id="condition-nvts",
        outcome=outcome,
        side=OrderSide.BUY,
        desired_price=Decimal("0.10"),
        quantity=Decimal("5"),
    )


def _rule() -> NumericThresholdRule:
    return NumericThresholdRule(
        rule_key="nvts-q2",
        source="earnings_resolution",
        subject="company:NVTS:earnings:2026Q2",
        metric="company.earnings.eps.non_gaap",
        comparison_op=">",
        strike=Decimal("-0.04"),
        rounding_places=2,
        yes_template=_template(Outcome.YES),
        no_template=_template(Outcome.NO),
    )


def _signal(value: object) -> ResolutionSignal:
    return ResolutionSignal(
        signal_id="earnings-simulation:nvts",
        source="earnings_resolution",
        subject="company:NVTS:earnings:2026Q2",
        metric="company.earnings.eps.non_gaap",
        value=value,
        detected_at=datetime.now(timezone.utc),
    )


class NumericThresholdStrategyTests(unittest.TestCase):
    def test_prepares_both_outcomes_and_selects_yes(self) -> None:
        strategy = NumericThresholdStrategy((_rule(),))

        self.assertEqual(
            [item.outcome for item in strategy.order_templates()],
            [Outcome.YES, Outcome.NO],
        )
        intents = strategy.evaluate(_signal(Decimal("-0.03")))

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].outcome, Outcome.YES)

    def test_strict_threshold_selects_no_on_equal_value(self) -> None:
        intents = NumericThresholdStrategy((_rule(),)).evaluate(
            _signal(Decimal("-0.04"))
        )

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].outcome, Outcome.NO)

    def test_rounds_half_up_before_comparison(self) -> None:
        strategy = NumericThresholdStrategy((_rule(),))

        self.assertEqual(
            strategy.evaluate(_signal(Decimal("-0.035")))[0].outcome,
            Outcome.NO,
        )
        self.assertEqual(
            strategy.evaluate(_signal(Decimal("-0.034")))[0].outcome,
            Outcome.YES,
        )

    def test_ignores_non_numeric_or_unrelated_signal(self) -> None:
        strategy = NumericThresholdStrategy((_rule(),))

        self.assertEqual(strategy.evaluate(_signal("unknown")), ())
        unrelated = ResolutionSignal(
            signal_id="other",
            source="earnings_resolution",
            subject="company:OTHER:earnings:2026Q2",
            metric="company.earnings.eps.non_gaap",
            value=Decimal("1"),
            detected_at=datetime.now(timezone.utc),
        )
        self.assertEqual(strategy.evaluate(unrelated), ())

    def test_rejects_wrong_template_outcome(self) -> None:
        with self.assertRaisesRegex(
            NumericThresholdConfigurationError,
            "must target YES",
        ):
            NumericThresholdRule(
                rule_key="bad",
                source="source",
                subject="subject",
                metric="metric",
                comparison_op=">",
                strike=Decimal("0"),
                rounding_places=2,
                yes_template=_template(Outcome.NO),
                no_template=_template(Outcome.NO),
            )


if __name__ == "__main__":
    unittest.main()
