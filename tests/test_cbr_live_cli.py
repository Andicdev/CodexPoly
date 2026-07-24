from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cbr_trading.execution import RemoteOrderState
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.market import MarketSnapshot
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

            def prepare(self, **kwargs: object) -> object:
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
            post_only=False,
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


class IsolatedOrderOverrideCliTests(unittest.TestCase):
    def test_preview_uses_one_shot_quantity_and_price_overrides(
        self,
    ) -> None:
        output = io.StringIO()
        repository = SimpleNamespace(
            load_active_cbr_rules=lambda: [
                {
                    "id": 102,
                    "rule_key": "cbr_increase_fast",
                    "condition_id": "condition-increase",
                    "account_name": "KinderSman",
                    "order_qty": "1000",
                    "yes_price": "0.999",
                    "no_price": "0.999",
                }
            ],
            close=lambda: None,
        )
        account_repository = SimpleNamespace(
            load_active=lambda _name: TradingAccountRecord(
                name="KinderSman",
                wallet_address="0x1234567890abcdef",
                venue="polymarket",
                is_active=True,
                encrypted_private_key=b"encrypted",
                signature_type=1,
            ),
            close=lambda: None,
        )
        snapshot = MarketSnapshot(
            condition_id="condition-increase",
            question="Will the key rate increase?",
            outcome="NO",
            token_id="token-no",
            best_bid=Decimal("0.001"),
            best_ask=Decimal("0.999"),
            last_trade_price=Decimal("0.50"),
            tick_size=Decimal("0.001"),
            minimum_order_size=Decimal("5"),
            neg_risk=False,
        )
        safety = LiveSafetySettings(
            trading_enabled=False,
            post_only=False,
            allowed_account="KinderSman",
            max_order_quantity=Decimal("5000"),
            max_notional=Decimal("5000"),
            max_total_notional=Decimal("5000"),
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
                cli,
                "SqlAlchemyTradingAccountRepository",
                return_value=account_repository,
            ),
            patch.object(
                cli.PolymarketMarketGateway,
                "load_snapshot",
                return_value=snapshot,
            ),
            patch.object(
                cli.LiveSafetySettings,
                "from_env",
                return_value=safety,
            ),
            redirect_stdout(output),
        ):
            exit_code = cli.main(
                [
                    "--rule-id",
                    "102",
                    "--action",
                    "NO",
                    "--quantity",
                    "100",
                    "--limit-price",
                    "0.999",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "preview")
        self.assertEqual(payload["rule"]["id"], 102)
        self.assertEqual(payload["order"]["outcome"], "NO")
        self.assertEqual(payload["order"]["quantity"], "100")
        self.assertEqual(payload["order"]["limit_price"], "0.999")
        self.assertEqual(payload["order"]["max_notional"], "99.900")
        self.assertFalse(payload["safety"]["ready_to_apply"])
        self.assertEqual(
            payload["safety"]["blockers"],
            ["live_trading_disabled"],
        )


class FullPathLiveTestCliTests(unittest.TestCase):
    def test_requires_explicit_confirmation_before_loading_rule(
        self,
    ) -> None:
        error = io.StringIO()
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
            ) as repository_class,
            redirect_stdout(io.StringIO()),
            patch("sys.stderr", error),
        ):
            exit_code = cli.main(
                [
                    "--full-path-live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--rule-id",
                    "102",
                    "--action",
                    "NO",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.10",
                ]
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 4)
        self.assertFalse(payload["order_submitted"])
        self.assertIn("--confirm-live-order", payload["error"])
        repository_class.assert_not_called()

    def test_rejects_invalid_numeric_override_without_traceback(
        self,
    ) -> None:
        error = io.StringIO()
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
            ) as repository_class,
            patch("sys.stderr", error),
        ):
            exit_code = cli.main(
                [
                    "--full-path-live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--rule-id",
                    "102",
                    "--action",
                    "NO",
                    "--quantity",
                    "not-a-number",
                    "--limit-price",
                    "0.10",
                    "--confirm-live-order",
                    "--cancel-after-test",
                ]
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 4)
        self.assertFalse(payload["order_submitted"])
        self.assertIn("invalid order_qty", payload["error"])
        repository_class.assert_not_called()

    def test_submits_through_warmed_reserved_batch_path(self) -> None:
        output = io.StringIO()
        stored_rule = {
            "id": 102,
            "rule_key": "cbr_increase_fast",
            "condition_id": "condition-increase",
            "account_name": "KinderSman",
            "order_qty": "1000",
            "order_price": "0.99",
            "params": {
                "order_price_yes": "0.999",
                "order_price_no": "0.999",
            },
        }
        repository = SimpleNamespace(
            load_active_cbr_rules=lambda: [stored_rule],
            close=lambda: None,
        )
        captured: dict[str, object] = {}
        inspections = iter(
            (
                SimpleNamespace(
                    snapshots=(
                        SimpleNamespace(
                            state=RemoteOrderState.OPEN,
                        ),
                    ),
                    failed_order_ids=(),
                ),
                SimpleNamespace(
                    snapshots=(
                        SimpleNamespace(
                            state=RemoteOrderState.CANCELLED,
                        ),
                    ),
                    failed_order_ids=(),
                ),
            )
        )

        class FakeCleanupGateway:
            def __init__(self, **kwargs: object):
                captured["cleanup_database_url"] = kwargs[
                    "database_url"
                ]
                captured["cleanup_safety"] = kwargs["safety"]

            def inspect_orders(self, **kwargs: object) -> object:
                captured.setdefault("inspections", []).append(kwargs)
                return next(inspections)

            def cancel_orders(self, **kwargs: object) -> object:
                captured["cancellation"] = kwargs
                return SimpleNamespace(
                    cancelled_order_ids=("order-123",),
                )

            def close(self) -> None:
                captured["cleanup_closed"] = True

        class FakeExecutor:
            def __init__(self, **kwargs: object):
                captured["subscriptions"] = kwargs["subscriptions"]
                captured["safety"] = kwargs["safety"]
                self.closed = False

            def prepare(self, *, release_url: str) -> object:
                captured["prepared_url"] = release_url
                return SimpleNamespace(outcome_count=2)

            def execute(
                self,
                intents: object,
                *,
                release: object,
            ) -> object:
                captured["intents"] = intents
                captured["release"] = release
                return [
                    SimpleNamespace(
                        status="MATCHED",
                        attempted=True,
                        success=True,
                        order_id="order-123",
                        error=None,
                    )
                ]

            def close(self) -> None:
                self.closed = True
                captured["closed"] = True

        safety = LiveSafetySettings(
            trading_enabled=True,
            post_only=False,
            allowed_account="KinderSman",
            max_order_quantity=Decimal("10"),
            max_notional=Decimal("10"),
            max_total_notional=Decimal("10"),
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
                "WarmLiveOrderExecutor",
                side_effect=FakeExecutor,
            ),
            patch.object(
                cli,
                "PolymarketSupervisionOrderGateway",
                side_effect=FakeCleanupGateway,
            ),
            redirect_stdout(output),
        ):
            exit_code = cli.main(
                [
                    "--full-path-live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--rule-id",
                    "102",
                    "--action",
                    "NO",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.10",
                    "--confirm-live-order",
                    "--cancel-after-test",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["prepared_outcomes"], 2)
        self.assertEqual(payload["result"]["order_id"], "order-123")
        self.assertTrue(payload["cleanup"]["confirmed_terminal"])
        self.assertTrue(payload["cleanup"]["cancel_requested"])
        self.assertTrue(payload["cleanup"]["cancel_acknowledged"])
        self.assertEqual(
            payload["cleanup"]["initial_state"],
            "OPEN",
        )
        self.assertEqual(
            payload["cleanup"]["final_state"],
            "CANCELLED",
        )
        self.assertEqual(
            captured["cancellation"],
            {
                "account_name": "KinderSman",
                "order_ids": ("order-123",),
            },
        )
        self.assertEqual(
            captured["prepared_url"],
            "cbr-live-test://smoke-001",
        )
        subscription = captured["subscriptions"][0]
        self.assertEqual(subscription["order_qty"], "5")
        self.assertEqual(
            subscription["params"]["order_price_no"],
            "0.10",
        )
        self.assertEqual(
            subscription["params"]["order_price_yes"],
            "0.999",
        )
        intent = captured["intents"][0]
        self.assertEqual(intent.action, "NO")
        self.assertEqual(intent.quantity, Decimal("5"))
        self.assertEqual(intent.limit_price, Decimal("0.10"))
        self.assertEqual(
            captured["release"].url,
            "cbr-live-test://smoke-001",
        )
        self.assertTrue(captured["closed"])
        self.assertTrue(captured["cleanup_closed"])

    def test_full_path_live_test_requires_exact_cleanup_opt_in(
        self,
    ) -> None:
        error = io.StringIO()
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
            ) as repository_class,
            patch("sys.stderr", error),
        ):
            exit_code = cli.main(
                [
                    "--full-path-live-test",
                    "--test-run-id",
                    "smoke-001",
                    "--rule-id",
                    "102",
                    "--action",
                    "NO",
                    "--quantity",
                    "5",
                    "--limit-price",
                    "0.10",
                    "--confirm-live-order",
                ]
            )

        payload = json.loads(error.getvalue())
        self.assertEqual(exit_code, 4)
        self.assertFalse(payload["order_submitted"])
        self.assertIn("--cancel-after-test", payload["error"])
        repository_class.assert_not_called()

    def test_cleanup_accepts_an_immediate_full_fill(self) -> None:
        cancel_orders = Mock()
        gateway = SimpleNamespace(
            inspect_orders=lambda **_kwargs: SimpleNamespace(
                snapshots=(
                    SimpleNamespace(
                        state=RemoteOrderState.FILLED,
                    ),
                ),
                failed_order_ids=(),
            ),
            cancel_orders=cancel_orders,
            close=lambda: None,
        )
        with patch.object(
            cli,
            "PolymarketSupervisionOrderGateway",
            return_value=gateway,
        ):
            cleanup = cli._cleanup_full_path_test_order(
                database_url="postgresql://unused",
                safety=_armed_safety(),
                account_name="KinderSman",
                order_id="order-filled",
            )

        self.assertTrue(cleanup["confirmed_terminal"])
        self.assertFalse(cleanup["cancel_requested"])
        self.assertEqual(cleanup["final_state"], "FILLED")
        cancel_orders.assert_not_called()

    def test_cleanup_fails_closed_when_final_state_is_unknown(
        self,
    ) -> None:
        inspections = iter(
            (
                SimpleNamespace(
                    snapshots=(),
                    failed_order_ids=("order-unknown",),
                ),
                SimpleNamespace(
                    snapshots=(
                        SimpleNamespace(
                            state=RemoteOrderState.UNKNOWN,
                        ),
                    ),
                    failed_order_ids=(),
                ),
            )
        )
        gateway = SimpleNamespace(
            inspect_orders=lambda **_kwargs: next(inspections),
            cancel_orders=lambda **_kwargs: SimpleNamespace(
                cancelled_order_ids=("order-unknown",),
            ),
            close=lambda: None,
        )
        with patch.object(
            cli,
            "PolymarketSupervisionOrderGateway",
            return_value=gateway,
        ):
            cleanup = cli._cleanup_full_path_test_order(
                database_url="postgresql://unused",
                safety=_armed_safety(),
                account_name="KinderSman",
                order_id="order-unknown",
            )

        self.assertFalse(cleanup["confirmed_terminal"])
        self.assertTrue(cleanup["cancel_requested"])
        self.assertEqual(cleanup["final_state"], "UNKNOWN")
        self.assertIn("not confirmed", cleanup["error"])


def _armed_safety() -> LiveSafetySettings:
    return LiveSafetySettings(
        trading_enabled=True,
        post_only=False,
        allowed_account="KinderSman",
        max_order_quantity=Decimal("10"),
        max_notional=Decimal("10"),
        max_total_notional=Decimal("10"),
        accounts_master_key="present",
    )


if __name__ == "__main__":
    unittest.main()
