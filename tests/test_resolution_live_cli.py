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
from cbr_trading.execution import (
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.live.safety import LiveSafetySettings
import cbr_trading.resolution_live.cli as cli


def _rule() -> dict:
    return {
        "id": 103,
        "type": "resolution_market",
        "ticker": "ANTHROPIC",
        "rule_key": "opus_yes",
        "status": "active",
        "account_name": "KinderSman",
        "condition_id": "0x" + ("7" * 64),
        "question": "Claude Opus by July 24?",
        "order_qty": 100,
        "order_price": 0.9,
        "params": {
            "source": "anthropic_official",
            "subject": "next_claude_opus",
            "metric": "public_release",
            "decision_mode": "fixed_outcome",
            "signal_value": True,
            "action": "YES",
            "order_price_yes": 0.9,
            "order_lifecycle": {"kind": "keep_open"},
        },
    }


class _Executor:
    def __init__(self, **_kwargs: object):
        self.maximum_notional = Decimal("90")
        self.details = (
            SimpleNamespace(
                template_id="fixed-outcome-rule:103:YES",
                outcome="YES",
                token_id="yes-token",
                quantity=Decimal("100"),
                desired_price=Decimal("0.9"),
                effective_price=Decimal("0.9"),
                tick_size=Decimal("0.001"),
                minimum_order_size=Decimal("5"),
                best_bid=Decimal("0.999"),
                best_ask=None,
                order_presigned=True,
                collateral_sufficient=True,
            ),
        )

    def prepare(self, templates: object, *, context: object) -> object:
        rows = tuple(templates)
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

    def execute(self, intents: object, *, signal: object) -> object:
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
        self.maximum_notional = Decimal("4.5")
        self.details = (
            SimpleNamespace(
                **{
                    **vars(self.details[0]),
                    "quantity": Decimal("5"),
                }
            ),
        )
        self.templates = ()
        self.cleanup_calls: list[dict] = []

    def prepare(self, templates: object, *, context: object) -> object:
        self.templates = tuple(templates)
        return super().prepare(self.templates, context=context)

    def execute(self, intents: object, *, signal: object) -> object:
        results = []
        for intent in intents:
            placed = PlacedOrder(
                order_id="order-live-1",
                asset_id="yes-token",
                effective_price=Decimal("0.9"),
                quantity=Decimal("5"),
            )
            handle = ExecutionHandle(
                order_group_id="group-live-1",
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


class ResolutionLiveCliTests(unittest.TestCase):
    def test_preflight_runs_manual_signal_without_submission(
        self,
    ) -> None:
        output = io.StringIO()
        repository = SimpleNamespace(
            load_active_rule=lambda rule_id: _rule(),
            close=lambda: None,
        )
        safety = LiveSafetySettings(
            trading_enabled=False,
            post_only=True,
            allowed_account="KinderSman",
            max_order_quantity=Decimal("200"),
            max_notional=Decimal("100"),
            max_total_notional=Decimal("100"),
            accounts_master_key="present",
        )
        with (
            patch.object(
                cli,
                "resolve_database_selection",
                return_value=SimpleNamespace(
                    url="postgresql://unused",
                    target="server_ext",
                    error=None,
                ),
            ),
            patch.object(
                cli,
                "SqlAlchemyRuleRepository",
                return_value=repository,
            ),
            patch.object(
                cli.LiveSafetySettings,
                "from_env",
                return_value=safety,
            ),
            patch.object(
                cli,
                "PolymarketPreflightPreparedExecutor",
                side_effect=_Executor,
            ),
            patch("sys.stdout", output),
        ):
            exit_code = cli.main(["--rule-id", "103"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["order_submitted"])
        self.assertTrue(payload["preparation"]["ready"])
        self.assertEqual(
            payload["manual_signal"]["selected_intents"],
            1,
        )
        self.assertEqual(
            payload["manual_signal"]["results"][0]["status"],
            "DRY_RUN",
        )
        self.assertTrue(payload["market"][0]["order_presigned"])

    def test_live_test_submits_override_then_confirms_cleanup(
        self,
    ) -> None:
        output = io.StringIO()
        repository = SimpleNamespace(
            load_active_rule=lambda rule_id: _rule(),
            close=lambda: None,
        )
        safety = LiveSafetySettings(
            trading_enabled=True,
            post_only=True,
            allowed_account="KinderSman",
            max_order_quantity=Decimal("5"),
            max_notional=Decimal("4.5"),
            max_total_notional=Decimal("4.5"),
            accounts_master_key="present",
        )
        live = _LiveExecutor()
        with (
            patch.object(
                cli,
                "resolve_database_selection",
                return_value=SimpleNamespace(
                    url="postgresql://unused",
                    target="server_ext",
                    error=None,
                ),
            ),
            patch.object(
                cli,
                "SqlAlchemyRuleRepository",
                return_value=repository,
            ),
            patch.object(
                cli.LiveSafetySettings,
                "from_env",
                return_value=safety,
            ),
            patch.object(
                cli,
                "PolymarketPreparedExecutor",
                return_value=live,
            ),
            patch.object(
                cli,
                "cleanup_exact_order",
                return_value={
                    "required": True,
                    "attempted": True,
                    "order_id": "order-live-1",
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
            exit_code = cli.main(
                [
                    "--rule-id",
                    "103",
                    "--live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.90",
                    "--confirm-live-order",
                    "--cancel-after-test",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["order_submitted"])
        self.assertEqual(
            live.templates[0].quantity,
            Decimal("5"),
        )
        self.assertEqual(
            live.templates[0].desired_price,
            Decimal("0.90"),
        )
        cleanup.assert_called_once()
        self.assertEqual(len(live.cleanup_calls), 1)
        self.assertTrue(payload["cleanup"]["audit_recorded"])

    def test_live_test_requires_all_explicit_guards(self) -> None:
        error = io.StringIO()
        with patch("sys.stderr", error):
            exit_code = cli.main(
                [
                    "--rule-id",
                    "103",
                    "--live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.90",
                ]
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("--confirm-live-order", payload["error"])


if __name__ == "__main__":
    unittest.main()
