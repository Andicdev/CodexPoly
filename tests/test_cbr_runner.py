from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, patch

from cbr_trading.client import DiscoveryResult
from cbr_trading.live.runner_executor import LivePreparationError
from cbr_trading.pipeline import PipelineOutcome
from cbr_trading.release import build_predicted_release_url
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
    release_url = build_predicted_release_url()
    return DiscoveryResult(
        ok=True,
        reason="published",
        url=release_url,
        request_url=f"{release_url}&_ts=1",
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


def _reprice_rule() -> dict:
    rule = _rule()
    rule["params"] = {
        **rule["params"],
        "order_lifecycle": {
            "kind": "reprice_on_tick_change",
            "old_tick": "0.01",
            "new_tick": "0.001",
            "max_reprices": 1,
        },
    }
    return rule


class RunnerRulePreloadTests(unittest.TestCase):
    def test_supervision_builder_checks_schema_without_migrating(self) -> None:
        settings = replace(
            _live_settings(),
            order_supervision_enabled=True,
            supervision_watch_refresh_interval=0.5,
            supervision_reconciliation_interval=15,
            supervision_reconciliation_stale_after=120,
            supervision_reconciliation_batch_size=25,
        )
        with (
            patch.object(
                runner,
                "SqlAlchemyOrderGroupRepository",
            ) as repository_class,
            patch.object(
                runner,
                "PolymarketSupervisionOrderGateway",
            ) as gateway_class,
            patch.object(
                runner,
                "PersistentOrderSupervisor",
            ) as supervisor_class,
            patch.object(
                runner,
                "OrderSupervisionRuntime",
            ) as runtime_class,
        ):
            runtime = runtime_class.return_value
            actual_runtime, actual_supervisor = (
                runner._build_order_supervision(
                    settings=settings,
                    safety=object(),
                    logger=runner.logging.getLogger(
                        "test.supervision-builder"
                    ),
                )
            )

        self.assertIs(actual_runtime, runtime)
        self.assertIs(
            actual_supervisor,
            supervisor_class.return_value,
        )
        repository_class.assert_called_once_with(
            database_url=settings.rules_database_url,
        )
        repository_class.return_value.migrate.assert_not_called()
        runtime.ensure_ready.assert_called_once_with()
        supervisor_class.assert_called_once_with(
            repository=repository_class.return_value,
            gateway=gateway_class.return_value,
            reconciliation_stale_after=timedelta(seconds=120),
            reconciliation_batch_size=25,
        )
        runtime_class.assert_called_once_with(
            repository=repository_class.return_value,
            supervisor=supervisor_class.return_value,
            watch_refresh_interval=0.5,
            reconciliation_interval=15,
            logger=ANY,
        )

    def test_not_published_keeps_discovery_result_shape(self) -> None:
        output = io.StringIO()
        release_url = build_predicted_release_url()
        waiting = DiscoveryResult(
            ok=False,
            reason="not_published_yet",
            url=release_url,
            request_url=f"{release_url}&_ts=1",
            status_code=404,
        )
        with (
            patch.object(runner, "_load_dotenv_if_available"),
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
            poller_class.return_value.run_once.return_value = waiting
            exit_code = runner.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "not_published_yet")
        self.assertNotIn("order_results", payload)

    def test_continuous_mode_uses_existing_until_published_poller(self) -> None:
        output = io.StringIO()
        settings = replace(_settings(), mode="live")
        with (
            patch.object(runner, "_load_dotenv_if_available"),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=settings,
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
            poller = poller_class.return_value
            poller.run_until_published.return_value = _release()
            exit_code = runner.main()

        self.assertEqual(exit_code, 0)
        poller.run_until_published.assert_called_once_with()
        poller.run_once.assert_not_called()

    def test_telegram_receives_compatible_pipeline_outcome(self) -> None:
        output = io.StringIO()
        settings = replace(
            _settings(),
            telegram_enabled=True,
            telegram_bot_token="configured",
            telegram_chat_id="configured",
        )
        with (
            patch.object(runner, "_load_dotenv_if_available"),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=settings,
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_rule()],
            ),
            patch.object(runner, "RequestsTransport"),
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            patch.object(runner, "TelegramNotifier") as notifier_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.return_value = _release()
            notifier = notifier_class.return_value
            notifier.notify_pipeline.return_value = SimpleNamespace(
                message_id=7
            )
            exit_code = runner.main()

        self.assertEqual(exit_code, 0)
        notifier.notify_pipeline.assert_called_once()
        outcome = notifier.notify_pipeline.call_args.args[0]
        self.assertIsInstance(outcome, PipelineOutcome)
        self.assertEqual(
            notifier.notify_pipeline.call_args.kwargs,
            {"dry_run": True},
        )

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
            def prepare(self, **kwargs: object) -> object:
                trace.append("prepare")
                return SimpleNamespace(
                    rule_count=1,
                    account_count=1,
                    outcome_count=2,
                    maximum_notional=20,
                    prepared_orders=(
                        SimpleNamespace(
                            rule_id=1,
                            rule_key="cbr_cut",
                            account_name="main",
                            condition_id="condition-1",
                            outcome="YES",
                            token_id="asset-yes",
                            quantity=Decimal("100"),
                            limit_price=Decimal("0.51"),
                        ),
                        SimpleNamespace(
                            rule_id=1,
                            rule_key="cbr_cut",
                            account_name="main",
                            condition_id="condition-1",
                            outcome="NO",
                            token_id="asset-no",
                            quantity=Decimal("100"),
                            limit_price=Decimal("0.51"),
                        ),
                    ),
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
            def prepare(self, **kwargs: object) -> object:
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

    def test_repricing_rule_is_blocked_when_supervision_is_disabled(
        self,
    ) -> None:
        output = io.StringIO()
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
                return_value=[_reprice_rule()],
            ),
            patch.object(
                runner,
                "WarmLiveOrderExecutor",
            ) as live_executor,
            patch.object(runner, "RequestsTransport"),
            patch.object(runner, "CbrClient"),
            patch.object(runner, "CbrPoller") as poller_class,
            redirect_stdout(output),
        ):
            poller_class.return_value.run_once.return_value = _release()
            exit_code = runner.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        live_executor.assert_not_called()
        self.assertEqual(
            payload["order_results"][0]["status"],
            "SKIPPED",
        )
        self.assertIn(
            "supervision is disabled",
            payload["order_results"][0]["error"],
        )

    def test_enabled_supervision_wraps_execution_and_owns_lifecycle(
        self,
    ) -> None:
        output = io.StringIO()
        trace: list[str] = []

        class FakeLiveExecutor:
            def prepare(self, **kwargs: object) -> object:
                trace.append("prepare")
                return SimpleNamespace(
                    rule_count=1,
                    account_count=1,
                    outcome_count=2,
                    maximum_notional=102,
                    prepared_orders=(
                        SimpleNamespace(
                            rule_id=1,
                            rule_key="cbr_cut",
                            account_name="main",
                            condition_id="condition-1",
                            outcome="YES",
                            token_id="asset-yes",
                            quantity=Decimal("100"),
                            limit_price=Decimal("0.51"),
                        ),
                        SimpleNamespace(
                            rule_id=1,
                            rule_key="cbr_cut",
                            account_name="main",
                            condition_id="condition-1",
                            outcome="NO",
                            token_id="asset-no",
                            quantity=Decimal("100"),
                            limit_price=Decimal("0.51"),
                        ),
                    ),
                )

            def execute(
                self,
                intents: list,
                *,
                release: DiscoveryResult,
            ) -> list:
                trace.append("execute")
                return [
                    SimpleNamespace(
                        intent=intents[0],
                        status="SUBMITTED",
                        attempted=True,
                        success=True,
                        order_id="order-1",
                        error=None,
                    )
                ]

            def close(self) -> None:
                trace.append("executor_close")

        class FakeSupervisor:
            def register(
                self,
                handle: object,
                *,
                policy: object,
            ) -> None:
                trace.append("register")

        class FakeRuntime:
            def start(self) -> None:
                trace.append("runtime_start")

            def release_when_idle(self) -> None:
                trace.append("runtime_release")

            def wait(self) -> None:
                trace.append("runtime_wait")

            def stop(self) -> None:
                trace.append("runtime_stop")

        settings = replace(
            _live_settings(),
            order_supervision_enabled=True,
        )
        runtime = FakeRuntime()
        supervisor = FakeSupervisor()
        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=settings,
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_reprice_rule()],
            ),
            patch.object(
                runner.LiveSafetySettings,
                "from_env",
                return_value=object(),
            ),
            patch.object(
                runner,
                "_build_order_supervision",
                return_value=(runtime, supervisor),
            ),
            patch.object(
                runner,
                "WarmLiveOrderExecutor",
                return_value=FakeLiveExecutor(),
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
        self.assertEqual(
            payload["order_results"][0]["status"],
            "SUBMITTED",
        )
        self.assertEqual(
            trace,
            [
                "runtime_start",
                "prepare",
                "poll",
                "execute",
                "register",
                "runtime_release",
                "runtime_wait",
                "executor_close",
                "runtime_stop",
            ],
        )

    def test_supervision_start_failure_prevents_live_preparation(
        self,
    ) -> None:
        output = io.StringIO()
        trace: list[str] = []

        class FakeLiveExecutor:
            def prepare(self, **kwargs: object) -> object:
                trace.append("prepare")
                raise AssertionError("live preparation must not run")

            def close(self) -> None:
                trace.append("executor_close")

        class FailingRuntime:
            def start(self) -> None:
                trace.append("runtime_start")
                raise RuntimeError("websocket runtime unavailable")

        settings = replace(
            _live_settings(),
            order_supervision_enabled=True,
        )
        with (
            patch.object(
                runner,
                "_load_dotenv_if_available",
            ),
            patch.object(
                runner.CbrSettings,
                "from_env",
                return_value=settings,
            ),
            patch.object(
                runner.SqlAlchemyRuleRepository,
                "load_active_cbr_rules",
                return_value=[_reprice_rule()],
            ),
            patch.object(
                runner.LiveSafetySettings,
                "from_env",
                return_value=object(),
            ),
            patch.object(
                runner,
                "_build_order_supervision",
                return_value=(FailingRuntime(), object()),
            ),
            patch.object(
                runner,
                "WarmLiveOrderExecutor",
                return_value=FakeLiveExecutor(),
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
        self.assertEqual(
            trace,
            ["runtime_start", "executor_close"],
        )
        self.assertEqual(
            payload["order_results"][0]["status"],
            "SKIPPED",
        )
        self.assertIn(
            "websocket runtime unavailable",
            payload["order_results"][0]["error"],
        )


if __name__ == "__main__":
    unittest.main()
