from __future__ import annotations

import unittest
from decimal import Decimal

from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.safety import (
    LiveSafetySettings,
    build_live_order_plan,
)


def _account() -> TradingAccountRecord:
    return TradingAccountRecord(
        name="kinderSman",
        wallet_address="0x1234567890abcdef1234567890abcdef1234abcd",
        venue="polymarket_clob",
        is_active=True,
        signature_type=2,
        encrypted_private_key=b"encrypted",
    )


def _snapshot(*, best_ask: str = "0.64") -> MarketSnapshot:
    return MarketSnapshot(
        condition_id="0x" + "a" * 64,
        question="CBR decrease?",
        outcome="YES",
        token_id="yes-token",
        best_bid=Decimal("0.61"),
        best_ask=Decimal(best_ask),
        last_trade_price=Decimal("0.63"),
        tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("5"),
        neg_risk=False,
    )


def _settings(**overrides: object) -> LiveSafetySettings:
    values: dict[str, object] = {
        "trading_enabled": True,
        "post_only": True,
        "allowed_account": "KinderSman",
        "max_order_quantity": Decimal("100"),
        "max_notional": Decimal("20"),
        "accounts_master_key": "master",
    }
    values.update(overrides)
    return LiveSafetySettings(**values)


class LiveSafetyTests(unittest.TestCase):
    def test_exact_safety_caps_allow_non_crossing_order(self) -> None:
        plan = build_live_order_plan(
            account=_account(),
            rule_id=98,
            rule_key="cbr_decrease_fast",
            quantity=Decimal("100"),
            limit_price=Decimal("0.20"),
            snapshot=_snapshot(),
            settings=_settings(),
        )

        self.assertTrue(plan.ready_to_apply)
        self.assertEqual(plan.notional, Decimal("20.00"))
        self.assertEqual(plan.blockers, ())
        self.assertTrue(plan.post_only)

    def test_disabled_missing_key_and_crossing_are_blockers(self) -> None:
        plan = build_live_order_plan(
            account=_account(),
            rule_id=98,
            rule_key="cbr_decrease_fast",
            quantity=Decimal("100"),
            limit_price=Decimal("0.64"),
            snapshot=_snapshot(),
            settings=_settings(
                trading_enabled=False,
                accounts_master_key=None,
                max_notional=Decimal("100"),
            ),
        )

        self.assertFalse(plan.ready_to_apply)
        self.assertIn("live_trading_disabled", plan.blockers)
        self.assertIn("accounts_master_key_missing", plan.blockers)
        self.assertIn("buy_would_cross_current_ask", plan.blockers)

    def test_quantity_and_notional_caps_fail_closed(self) -> None:
        plan = build_live_order_plan(
            account=_account(),
            rule_id=98,
            rule_key="cbr_decrease_fast",
            quantity=Decimal("101"),
            limit_price=Decimal("0.21"),
            snapshot=_snapshot(),
            settings=_settings(),
        )

        self.assertIn("max_order_qty_exceeded", plan.blockers)
        self.assertIn("max_notional_exceeded", plan.blockers)


if __name__ == "__main__":
    unittest.main()
