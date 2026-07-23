from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from cbr_trading.live.safety import LiveSafetySettings
import cbr_trading.live.cli as cli


class RunnerPreflightCliTests(unittest.TestCase):
    def test_runner_preflight_never_submits_an_order(self) -> None:
        output = io.StringIO()

        repository = SimpleNamespace(
            load_active_cbr_rules=lambda: [{"id": 98}],
            close=lambda: None,
        )

        class FakeExecutor:
            def __init__(self):
                self.closed = False

            def prepare(self) -> object:
                return SimpleNamespace(
                    rule_count=1,
                    account_count=1,
                    outcome_count=2,
                    maximum_notional=Decimal("20"),
                )

            def close(self) -> None:
                self.closed = True

        executor = FakeExecutor()
        safety = LiveSafetySettings(
            trading_enabled=False,
            post_only=True,
            allowed_account="kinderSman",
            max_order_quantity=Decimal("100"),
            max_notional=Decimal("20"),
            max_total_notional=Decimal("20"),
            accounts_master_key="present",
        )

        with (
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
                "WarmLiveOrderExecutor",
                return_value=executor,
            ) as executor_class,
            redirect_stdout(output),
        ):
            exit_code = cli._run_runner_preflight(
                database_url="postgresql://unused",
                database_target="server_ext",
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["order_submitted"])
        self.assertFalse(
            payload["safety"]["live_trading_enabled"]
        )
        self.assertTrue(executor.closed)
        validation_safety = executor_class.call_args.kwargs["safety"]
        self.assertTrue(validation_safety.trading_enabled)


if __name__ == "__main__":
    unittest.main()
