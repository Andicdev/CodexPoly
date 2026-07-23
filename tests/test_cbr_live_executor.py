from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.executor import (
    LiveOrderError,
    LiveOrderExecutor,
)
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.safety import (
    LiveSafetySettings,
    build_live_order_plan,
)


CONDITION_ID = "0x" + "a" * 64
WALLET = "0x1234567890abcdef1234567890abcdef1234abcd"


def _account() -> TradingAccountRecord:
    return TradingAccountRecord(
        name="kinderSman",
        wallet_address=WALLET,
        venue="polymarket_clob",
        is_active=True,
        signature_type=2,
        encrypted_private_key=b"encrypted",
    )


def _settings() -> LiveSafetySettings:
    return LiveSafetySettings(
        trading_enabled=True,
        post_only=True,
        allowed_account="kinderSman",
        max_order_quantity=Decimal("100"),
        max_notional=Decimal("20"),
        accounts_master_key="master",
    )


def _plan() -> object:
    snapshot = MarketSnapshot(
        condition_id=CONDITION_ID,
        question="CBR decrease?",
        outcome="YES",
        token_id="yes-token",
        best_bid=Decimal("0.61"),
        best_ask=Decimal("0.64"),
        last_trade_price=Decimal("0.63"),
        tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("5"),
        neg_risk=False,
    )
    return build_live_order_plan(
        account=_account(),
        rule_id=98,
        rule_key="cbr_decrease_fast",
        quantity=Decimal("100"),
        limit_price=Decimal("0.20"),
        snapshot=snapshot,
        settings=_settings(),
    )


class _Client:
    def __init__(self, *, best_ask: str = "0.64"):
        self.wallet = WALLET.upper()
        self.wallet_type = "GNOSIS_SAFE"
        self.best_ask = best_ask
        self.place_kwargs: dict[str, object] | None = None
        self.closed = False

    def get_order_book(self, *, token_id: str) -> object:
        return SimpleNamespace(
            condition_id=CONDITION_ID,
            tick_size="0.01",
            min_order_size="5",
            asks=(SimpleNamespace(price=self.best_ask),),
        )

    def get_balance_allowance(self, *, asset_type: str) -> object:
        self.balance_asset_type = asset_type
        return SimpleNamespace(
            balance=50_000_000,
            allowances={},
        )

    def place_limit_order(self, **kwargs: object) -> object:
        self.place_kwargs = kwargs
        return SimpleNamespace(
            ok=True,
            order_id="order-123",
            status="live",
        )

    def close(self) -> None:
        self.closed = True


class LiveExecutorTests(unittest.TestCase):
    def test_places_only_post_only_buy_after_fresh_book_check(
        self,
    ) -> None:
        client = _Client()

        def factory(private_key: str, wallet: str) -> _Client:
            self.assertEqual(private_key, "private")
            self.assertEqual(wallet, WALLET)
            return client

        executor = LiveOrderExecutor(
            client_factory=factory,
            decryptor=lambda encrypted, master: "private",
        )
        result = executor.place(
            plan=_plan(),
            account=_account(),
            settings=_settings(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_id, "order-123")
        self.assertEqual(result.collateral_balance, Decimal("50"))
        self.assertEqual(
            client.place_kwargs,
            {
                "token_id": "yes-token",
                "price": "0.20",
                "size": "100",
                "side": "BUY",
                "post_only": True,
            },
        )
        self.assertTrue(client.closed)

    def test_stale_crossing_book_skips_submission(self) -> None:
        client = _Client(best_ask="0.20")
        executor = LiveOrderExecutor(
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, master: "private",
        )

        with self.assertRaisesRegex(
            LiveOrderError,
            "cross",
        ):
            executor.place(
                plan=_plan(),
                account=_account(),
                settings=_settings(),
            )

        self.assertIsNone(client.place_kwargs)
        self.assertTrue(client.closed)

    def test_wallet_signature_mismatch_skips_submission(self) -> None:
        client = _Client()
        client.wallet_type = "POLY_PROXY"
        executor = LiveOrderExecutor(
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, master: "private",
        )

        with self.assertRaisesRegex(
            LiveOrderError,
            "signature type",
        ):
            executor.place(
                plan=_plan(),
                account=_account(),
                settings=_settings(),
            )

        self.assertIsNone(client.place_kwargs)


if __name__ == "__main__":
    unittest.main()
