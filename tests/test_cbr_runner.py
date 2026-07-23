from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from cbr_trading.client import DiscoveryResult
from cbr_trading.live.runner_executor import LivePreparationError
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


def _live_settings() -> CbrSettings:
    return CbrSettings(
        mode="live_once",
        dry_run=False,
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

    def test_live_executor_is_warmed_before_polling(self) -> None:
        output = io.StringIO()
        trace: list[str] = []

        class FakeLiveExecutor:
            def prepare(self) -> object:
                trace.append("prepare")
                return SimpleNamespace(
                    rule_count=1,
                    account_count=1,
                    outcome_count=2,
                    maximum_notional=20,
                )

            def execute(
                self,
                intents: list,
                *,
                release: DiscoveryResult,
            ) -> list:
                trace.append("execute")
                return []

            def close(self) -> None:
                trace.append("close")

        live_executor = FakeLiveExecutor()
        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=_live_settings(),
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_rule()],
            ),
            patch.object(
                runner.LiveSafetySettings,
                "from_env",
                return_value=object(),
            ),
            patch.object(
                runner,
                "WarmLiveOrderExecutor",
                return_value=live_executor,
            ),
            patch.object(runner, "RequestsTransport"),
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.side_effect = (
                lambda: trace.append("poll") or _release()
            )
            exit_code = runner.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(trace, ["prepare", "poll", "execute", "close"])

    def test_live_preparation_failure_still_monitors(self) -> None:
        output = io.StringIO()
        trace: list[str] = []

        class FailingLiveExecutor:
            def prepare(self) -> object:
                trace.append("prepare")
                raise LivePreparationError("ledger missing")

            def close(self) -> None:
                trace.append("close")

        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=_live_settings(),
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_rule()],
            ),
            patch.object(
                runner.LiveSafetySettings,
                "from_env",
                return_value=object(),
            ),
            patch.object(
                runner,
                "WarmLiveOrderExecutor",
                return_value=FailingLiveExecutor(),
            ),
            patch.object(runner, "RequestsTransport"),
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.side_effect = (
                lambda: trace.append("poll") or _release()
            )
            exit_code = runner.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(trace, ["prepare", "close", "poll"])
        self.assertEqual(payload["order_results"][0]["status"], "SKIPPED")
        self.assertIn(
            "ledger missing",
            payload["order_results"][0]["error"],
        )


if __name__ == "__main__":
    unittest.main()
