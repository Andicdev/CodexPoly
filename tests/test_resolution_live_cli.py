from __future__ import annotations

import io
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from cbr_trading.domain import ExecutionStatus, OrderExecutionResult
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


if __name__ == "__main__":
    unittest.main()
