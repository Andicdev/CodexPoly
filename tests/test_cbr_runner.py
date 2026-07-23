from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cbr_trading.client import DiscoveryResult
from cbr_trading.rule_repository import RuleLoadError
from cbr_trading.settings import CbrSettings
import cbr_trading.runner as runner


def _settings() -> CbrSettings:
    return CbrSettings(
        mode="live_once",
        previous_rate=14.5,
        rules_db_enabled=True,
        rules_database_url="postgresql://unused",
        telegram_enabled=False,
    )


def _release() -> DiscoveryResult:
    return DiscoveryResult(
        ok=True,
        reason="published",
        url="https://www.cbr.ru/release",
        request_url="https://www.cbr.ru/release?_ts=1",
        status_code=200,
        title=(
            "Bank of Russia cuts the key rate by 25 bp "
            "to 14.25% p.a."
        ),
        new_rate=14.25,
    )


def _rule() -> dict:
    return {
        "id": 1,
        "rule_key": "cbr_cut",
        "account_name": "main",
        "condition_id": "condition-1",
        "order_qty": 100,
        "order_price": 0.51,
        "params": {
            "metric_key": "cbr_key_rate_change_bp",
            "execution_path": "fast",
            "threshold": -25,
            "cmp": "<=",
            "decision_mode": "binary_yes_no",
        },
    }


class RunnerRulePreloadTests(unittest.TestCase):
    def test_database_failure_continues_without_trading(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=_settings(),
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                side_effect=RuleLoadError("read failed"),
            ),
            patch.object(runner, "RequestsTransport") as transport,
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.return_value = _release()
            exit_code = runner.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        transport.assert_called_once()
        self.assertEqual(payload["rules_load_error"], "read failed")
        self.assertEqual(payload["evaluations"], [])
        self.assertEqual(payload["order_results"], [])

    def test_preloaded_rules_reach_pipeline(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=_settings(),
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_rule()],
            ),
            patch.object(runner, "RequestsTransport"),
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.return_value = _release()
            exit_code = runner.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["change_bps"], -25)
        self.assertEqual(len(payload["evaluations"]), 1)
        self.assertEqual(
            payload["order_results"][0]["status"],
            "DRY_RUN",
        )


if __name__ == "__main__":
    unittest.main()
