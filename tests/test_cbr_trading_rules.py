from __future__ import annotations

import unittest

from cbr_trading.trading_rules import (
    compare,
    evaluate_rule,
    evaluate_rules,
)


def _subscription(
    *,
    threshold: object = 0,
    operator: str = ">=",
    decision_mode: str = "binary_yes_no",
    base_price: object = 0.5,
    yes_price: object | None = None,
    no_price: object | None = None,
) -> dict:
    params = {
        "threshold": threshold,
        "cmp": operator,
        "decision_mode": decision_mode,
    }
    if yes_price is not None:
        params["order_price_yes"] = yes_price
    if no_price is not None:
        params["order_price_no"] = no_price
    return {
        "id": 7,
        "rule_key": "cbr_test",
        "params": params,
        "order_price": base_price,
    }


class ComparisonTests(unittest.TestCase):
    def test_all_legacy_comparison_aliases(self) -> None:
        cases = [
            (">", 2, 1, True),
            ("gt", 2, 1, True),
            (">=", 1, 1, True),
            ("ge", 1, 1, True),
            ("<", 1, 2, True),
            ("lt", 1, 2, True),
            ("<=", 2, 2, True),
            ("le", 2, 2, True),
            ("==", 2, 2, True),
            ("eq", 2, 2, True),
            ("!=", 2, 3, True),
            ("ne", 2, 3, True),
        ]
        for operator, value, threshold, expected in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    compare(value, threshold, operator),
                    expected,
                )

    def test_unknown_operator_preserves_legacy_greater_equal_default(
        self,
    ) -> None:
        self.assertTrue(compare(2, 1, "unknown"))
        self.assertFalse(compare(0, 1, "unknown"))


class DecisionModeTests(unittest.TestCase):
    def test_binary_yes_no(self) -> None:
        yes = evaluate_rule(
            100,
            _subscription(threshold=50),
        )
        no = evaluate_rule(
            0,
            _subscription(threshold=50),
        )
        self.assertEqual(yes.action, "YES")
        self.assertEqual(no.action, "NO")

    def test_binary_no_yes_inverts_action(self) -> None:
        passed = evaluate_rule(
            100,
            _subscription(
                threshold=50,
                decision_mode="binary_no_yes",
            ),
        )
        failed = evaluate_rule(
            0,
            _subscription(
                threshold=50,
                decision_mode="binary_no_yes",
            ),
        )
        self.assertEqual(passed.action, "NO")
        self.assertEqual(failed.action, "YES")

    def test_yes_only_skips_when_condition_fails(self) -> None:
        result = evaluate_rule(
            0,
            _subscription(
                threshold=50,
                decision_mode="yes_only",
            ),
        )
        self.assertFalse(result.should_trade)
        self.assertEqual(result.reason, "yes_only_not_passed")

    def test_no_only_trades_no_when_condition_passes(self) -> None:
        result = evaluate_rule(
            100,
            _subscription(
                threshold=50,
                decision_mode="no_only",
            ),
        )
        self.assertTrue(result.should_trade)
        self.assertEqual(result.action, "NO")

    def test_no_only_on_not_passed(self) -> None:
        skipped = evaluate_rule(
            100,
            _subscription(
                threshold=50,
                decision_mode="no_only_on_not_passed",
            ),
        )
        selected = evaluate_rule(
            0,
            _subscription(
                threshold=50,
                decision_mode="no_only_on_not_passed",
            ),
        )
        self.assertFalse(skipped.should_trade)
        self.assertEqual(
            skipped.reason,
            "no_only_on_not_passed_but_passed",
        )
        self.assertEqual(selected.action, "NO")

    def test_unknown_mode_preserves_binary_yes_no_default(self) -> None:
        result = evaluate_rule(
            100,
            _subscription(
                threshold=50,
                decision_mode="future_unknown_mode",
            ),
        )
        self.assertEqual(result.action, "YES")


class RuleValidationAndPriceTests(unittest.TestCase):
    def test_missing_and_bad_threshold_are_skipped(self) -> None:
        missing = _subscription()
        missing["params"].pop("threshold")
        bad = _subscription(threshold="not-a-number")

        missing_result = evaluate_rule(1, missing)
        bad_result = evaluate_rule(1, bad)

        self.assertEqual(missing_result.reason, "missing_threshold")
        self.assertEqual(bad_result.reason, "bad_threshold")
        self.assertFalse(missing_result.should_trade)
        self.assertFalse(bad_result.should_trade)

    def test_uses_action_specific_prices(self) -> None:
        yes = evaluate_rule(
            10,
            _subscription(
                threshold=1,
                base_price=0.5,
                yes_price=0.91,
                no_price=0.09,
            ),
        )
        no = evaluate_rule(
            0,
            _subscription(
                threshold=1,
                base_price=0.5,
                yes_price=0.91,
                no_price=0.09,
            ),
        )
        self.assertEqual(yes.order_price, 0.91)
        self.assertEqual(no.order_price, 0.09)

    def test_invalid_action_price_falls_back_to_base_price(self) -> None:
        result = evaluate_rule(
            10,
            _subscription(
                threshold=1,
                base_price="0.55",
                yes_price="invalid",
            ),
        )
        self.assertEqual(result.order_price, 0.55)

    def test_multiple_rules_preserve_input_order(self) -> None:
        first = _subscription(threshold=1)
        first["id"] = 10
        second = _subscription(threshold=2)
        second["id"] = 20

        results = evaluate_rules(5, [first, second])

        self.assertEqual(
            [result.rule_id for result in results],
            [10, 20],
        )


if __name__ == "__main__":
    unittest.main()
