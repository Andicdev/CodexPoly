from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from cbr_trading.mstr_btc import (
    MSTR_PURCHASE_ANY_SIGNAL_ID,
    MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
    MSTR_SALE_ANY_SIGNAL_ID,
)
from cbr_trading.simulations import mstr_btc_resolution as simulation


class MstrBtcResolutionSimulationTests(unittest.TestCase):
    def test_default_matrix_runs_nine_non_submitting_decisions(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            exit_code = simulation.main(["--run-id", "unit-mstr-001"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["parser_bypassed"])
        self.assertFalse(payload["database_used"])
        self.assertFalse(payload["profile_persisted"])
        self.assertFalse(payload["production_scope_claimed"])
        self.assertFalse(payload["order_submitted"])
        self.assertEqual(payload["scenario_count"], 3)
        self.assertEqual(payload["market_decision_count"], 9)
        self.assertEqual(
            payload["path"],
            [
                "MstrBtcResolutionSource",
                "ResolutionSignal",
                "NumericThresholdStrategy",
                "OrderIntent",
                "DryRunPreparedExecutor",
            ],
        )
        for scenario in payload["scenarios"]:
            self.assertTrue(scenario["ok"])
            self.assertEqual(len(scenario["markets"]), 3)
            for market in scenario["markets"]:
                self.assertTrue(market["ok"])
                self.assertEqual(
                    market["prepared_template_count"],
                    2,
                )
                self.assertEqual(market["desired_price"], "0.999")
                self.assertEqual(market["quantity"], "50")
                self.assertEqual(
                    market["lifecycle_policy"],
                    "reprice_on_tick_change",
                )
                self.assertEqual(
                    market["execution_status"],
                    "DRY_RUN",
                )
                self.assertFalse(market["execution_attempted"])
                self.assertFalse(market["order_submitted"])
                self.assertNotEqual(
                    market["production_signal_id"],
                    market["simulation_scope_id"],
                )

    def test_purchase_over_1000_selects_expected_three_outcomes(self) -> None:
        payload = simulation.run_mstr_btc_dry_run(
            run_id="unit-mstr-002",
        )

        scenario = self._scenario(payload, "purchase_over_1000")
        outcomes = self._outcomes(scenario)
        self.assertEqual(outcomes[MSTR_PURCHASE_ANY_SIGNAL_ID], "YES")
        self.assertEqual(
            outcomes[MSTR_PURCHASE_OVER_1000_SIGNAL_ID],
            "YES",
        )
        self.assertEqual(outcomes[MSTR_SALE_ANY_SIGNAL_ID], "NO")

    def test_exact_1000_obeys_strict_boundary(self) -> None:
        payload = simulation.run_mstr_btc_dry_run(
            run_id="unit-mstr-003",
        )

        scenario = self._scenario(payload, "purchase_exactly_1000")
        outcomes = self._outcomes(scenario)
        self.assertEqual(outcomes[MSTR_PURCHASE_ANY_SIGNAL_ID], "YES")
        self.assertEqual(
            outcomes[MSTR_PURCHASE_OVER_1000_SIGNAL_ID],
            "NO",
        )
        self.assertEqual(outcomes[MSTR_SALE_ANY_SIGNAL_ID], "NO")

    def test_sale_selects_only_sale_market_yes(self) -> None:
        payload = simulation.run_mstr_btc_dry_run(
            run_id="unit-mstr-004",
        )

        scenario = self._scenario(payload, "sale")
        outcomes = self._outcomes(scenario)
        self.assertEqual(outcomes[MSTR_PURCHASE_ANY_SIGNAL_ID], "NO")
        self.assertEqual(
            outcomes[MSTR_PURCHASE_OVER_1000_SIGNAL_ID],
            "NO",
        )
        self.assertEqual(outcomes[MSTR_SALE_ANY_SIGNAL_ID], "YES")

    def test_unsafe_run_id_fails_closed(self) -> None:
        error = io.StringIO()
        with patch("sys.stderr", error):
            exit_code = simulation.main(
                ["--run-id", "unsafe id"],
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 5)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["order_submitted"])

    @staticmethod
    def _scenario(payload: dict, name: str) -> dict:
        return next(
            row for row in payload["scenarios"] if row["name"] == name
        )

    @staticmethod
    def _outcomes(scenario: dict) -> dict[str, str]:
        return {
            row["production_signal_id"]: row["selected_outcome"]
            for row in scenario["markets"]
        }


if __name__ == "__main__":
    unittest.main()
