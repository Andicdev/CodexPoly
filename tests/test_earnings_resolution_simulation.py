from __future__ import annotations

import io
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from cbr_trading.domain import (
    ExecutionHandle,
    ExecutionStatus,
    OrderExecutionResult,
    PlacedOrder,
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


class _LiveExecutor(_Executor):
    def __init__(self, **kwargs: object):
        super().__init__(**kwargs)
        self.cleanup_calls: list[dict] = []

    def execute(self, intents: object, *, signal: object) -> tuple:
        results = []
        for intent in intents:
            placed = PlacedOrder(
                order_id="nvts-live-order-1",
                asset_id="yes-token",
                effective_price=intent.desired_price,
                quantity=intent.quantity,
            )
            handle = ExecutionHandle(
                order_group_id="nvts-live-group-1",
                intent_id=intent.intent_id,
                signal_id=intent.signal_id,
                template_id=intent.template_id,
                strategy_id=intent.strategy_id,
                account_name=intent.account_name,
                condition_id=intent.condition_id,
                outcome=intent.outcome,
                side=intent.side,
                asset_id=placed.asset_id,
                desired_price=intent.desired_price,
                quantity=intent.quantity,
                live_order_ids=(placed.order_id,),
            )
            results.append(
                OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.SUBMITTED,
                    attempted=True,
                    orders=(placed,),
                    handle=handle,
                )
            )
        return tuple(results)

    def record_cleanup(
        self,
        *,
        template_id: str,
        cleanup: object,
    ) -> None:
        self.cleanup_calls.append(
            {
                "template_id": template_id,
                "cleanup": cleanup,
            }
        )


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

    def test_live_test_submits_selected_outcome_and_cleans_exact_id(
        self,
    ) -> None:
        output = io.StringIO()
        safety = LiveSafetySettings(
            trading_enabled=True,
            post_only=True,
            allowed_account="test-account",
            max_order_quantity=Decimal("5"),
            max_notional=Decimal("0.50"),
            max_total_notional=Decimal("1.00"),
            accounts_master_key="present",
        )
        live = _LiveExecutor()
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
                "PolymarketPreparedExecutor",
                return_value=live,
            ),
            patch.object(
                simulation,
                "cleanup_exact_order",
                return_value={
                    "required": True,
                    "attempted": True,
                    "order_id": "nvts-live-order-1",
                    "cancel_requested": True,
                    "cancel_acknowledged": True,
                    "initial_state": "OPEN",
                    "final_state": "CANCELLED",
                    "confirmed_terminal": True,
                    "error": None,
                },
            ) as cleanup,
            patch("sys.stdout", output),
        ):
            exit_code = simulation.main(
                [
                    "--eps=-0.03",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.10",
                    "--run-id",
                    "test-live-001",
                    "--live-test",
                    "--expected-outcome",
                    "YES",
                    "--confirm-live-order",
                    "--cancel-after-test",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["order_submitted"])
        self.assertEqual(
            payload["mode"],
            "earnings_resolution_live_test",
        )
        self.assertEqual(
            payload["resolution"]["selected_outcome"],
            "YES",
        )
        cleanup.assert_called_once()
        self.assertEqual(len(live.cleanup_calls), 1)
        self.assertTrue(payload["cleanup"]["confirmed_terminal"])
        self.assertTrue(payload["cleanup"]["audit_recorded"])

    def test_live_test_requires_every_explicit_guard(self) -> None:
        error = io.StringIO()
        with patch("sys.stderr", error):
            exit_code = simulation.main(
                [
                    "--eps=-0.03",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.10",
                    "--run-id",
                    "test-live-002",
                    "--live-test",
                    "--expected-outcome",
                    "YES",
                    "--cancel-after-test",
                ]
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("--confirm-live-order", payload["error"])

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
