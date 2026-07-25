from __future__ import annotations

import io
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from cbr_trading.domain import (
    ExecutionStatus,
    OrderExecutionResult,
)
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.execution import (
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.live.safety import LiveSafetySettings
import cbr_trading.simulations.earnings_resolution as simulation


class _Store:
    def __init__(self, **_kwargs: object):
        self.closed = False

    def ensure_ready(self) -> None:
        return None

    def load_active_rules(self) -> tuple:
        return (nvts_q2_2026_shadow_rule(),)

    def close(self) -> None:
        self.closed = True


class _Executor:
    def __init__(self, **_kwargs: object):
        self.maximum_notional = Decimal("1.00")
        self.details = ()

    def prepare(self, templates: object, *, context: object) -> object:
        rows = tuple(templates)
        self.details = tuple(
            SimpleNamespace(
                template_id=row.template_id,
                outcome=row.outcome.value,
                quantity=row.quantity,
                desired_price=row.desired_price,
                effective_price=row.desired_price,
                tick_size=Decimal("0.01"),
                minimum_order_size=Decimal("5"),
                best_bid=(
                    Decimal("0.37")
                    if row.outcome.value == "YES"
                    else Decimal("0.62")
                ),
                best_ask=(
                    Decimal("0.38")
                    if row.outcome.value == "YES"
                    else Decimal("0.63")
                ),
                order_presigned=True,
                collateral_sufficient=True,
            )
            for row in rows
        )
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=row.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=f"prepared:{row.template_id}",
                )
                for row in rows
            ),
            context=context,
        )

    def execute(self, intents: object, *, signal: object) -> tuple:
        return tuple(
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.DRY_RUN,
                attempted=False,
            )
            for intent in intents
        )

    def close(self) -> None:
        return None


class EarningsResolutionSimulationTests(unittest.TestCase):
    def test_runs_real_source_strategy_and_executor_for_yes(self) -> None:
        exit_code, payload = self._run(
            eps="-0.03",
            run_id="test-yes-001",
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["parser_bypassed"])
        self.assertFalse(payload["synthetic_fact_persisted"])
        self.assertFalse(payload["order_submitted"])
        self.assertEqual(
            payload["simulation"]["expected_outcome"],
            "YES",
        )
        self.assertEqual(
            payload["resolution"]["selected_outcome"],
            "YES",
        )
        self.assertEqual(
            payload["resolution"]["observed_signals"],
            1,
        )
        self.assertEqual(
            payload["resolution"]["selected_intents"],
            1,
        )
        self.assertEqual(len(payload["preparation"]["items"]), 2)
        self.assertEqual(
            payload["resolution"]["results"][0]["status"],
            "DRY_RUN",
        )

    def test_strict_boundary_selects_no(self) -> None:
        exit_code, payload = self._run(
            eps="-0.04",
            run_id="test-no-001",
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["simulation"]["expected_outcome"],
            "NO",
        )
        self.assertEqual(
            payload["resolution"]["selected_outcome"],
            "NO",
        )

    def _run(
        self,
        *,
        eps: str,
        run_id: str,
    ) -> tuple[int, dict]:
        output = io.StringIO()
        safety = LiveSafetySettings(
            trading_enabled=False,
            post_only=True,
            allowed_account="test-account",
            max_order_quantity=Decimal("5"),
            max_notional=Decimal("0.50"),
            max_total_notional=Decimal("1.00"),
            accounts_master_key="present",
        )
        with (
            patch.object(
                simulation,
                "resolve_database_selection",
                return_value=SimpleNamespace(
                    url="postgresql://unused",
                    target="server_ext",
                    error=None,
                ),
            ),
            patch.object(
                simulation,
                "SqlAlchemyEarningsStore",
                side_effect=_Store,
            ),
            patch.object(
                simulation.LiveSafetySettings,
                "from_env",
                return_value=safety,
            ),
            patch.object(
                simulation,
                "PolymarketPreflightPreparedExecutor",
                side_effect=_Executor,
            ),
            patch("sys.stdout", output),
        ):
            exit_code = simulation.main(
                [
                    "--eps",
                    eps,
                    "--run-id",
                    run_id,
                ]
            )
        return exit_code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()
