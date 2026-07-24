from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.client import DiscoveryResult
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.idempotency import ExecutionClaim
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.runner_executor import (
    UnavailableLiveOrderExecutor,
    WarmLiveOrderExecutor,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.pipeline import OrderIntent


CONDITION_ID = "0x" + ("a" * 64)
WALLET = "0x" + ("b" * 40)


def _subscription() -> dict:
    return {
        "id": 98,
        "rule_key": "cbr_decrease_fast",
        "account_name": "KinderSman",
        "condition_id": CONDITION_ID,
        "order_qty": 100,
        "order_price": 0.20,
        "params": {
            "threshold": 0,
            "cmp": "<",
            "decision_mode": "binary_yes_no",
        },
    }


def _intent(*, action: str = "YES") -> OrderIntent:
    return OrderIntent(
        rule_id=98,
        rule_key="cbr_decrease_fast",
        account_name="KinderSman",
        condition_id=CONDITION_ID,
        action=action,
        quantity=100,
        limit_price=0.20,
        ready=True,
        reason="ready",
    )


def _release() -> DiscoveryResult:
    return DiscoveryResult(
        ok=True,
        reason="published",
        url="https://www.cbr.ru/eng/press/pr/?file=release",
        request_url="https://www.cbr.ru/eng/press/pr/?file=release&_ts=1",
        status_code=200,
        title="Bank of Russia cuts the key rate to 14.00% p.a.",
        new_rate=14.0,
    )


def _safety() -> LiveSafetySettings:
    return LiveSafetySettings(
        trading_enabled=True,
        post_only=False,
        allowed_account="kinderSman",
        max_order_quantity=Decimal("100"),
        max_notional=Decimal("20"),
        max_total_notional=Decimal("20"),
        accounts_master_key="test-master-key",
    )


class _AccountRepository:
    def __init__(self):
        self.loads = 0
        self.closed = False

    def load_active(self, account_name: str) -> TradingAccountRecord:
        self.loads += 1
        return TradingAccountRecord(
            name="kinderSman",
            wallet_address=WALLET,
            venue="polymarket_clob",
            is_active=True,
            signature_type=2,
            encrypted_private_key=b"encrypted",
        )

    def close(self) -> None:
        self.closed = True


class _MarketGateway:
    def load_snapshot(
        self,
        *,
        condition_id: str,
        outcome: str,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            condition_id=condition_id,
            question="Will the Bank of Russia decrease rates?",
            outcome=outcome,
            token_id=f"token-{outcome.lower()}",
            best_bid=Decimal("0.10"),
            best_ask=Decimal("0.60"),
            last_trade_price=Decimal("0.30"),
            tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("5"),
            neg_risk=False,
        )


class _Ledger:
    def __init__(self, *, acquired: bool = True):
        self.acquired = acquired
        self.ready_checks = 0
        self.claims: list[str] = []
        self.completions: list[dict] = []
        self.closed = False

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def claim(
        self,
        *,
        release_url: str,
        intent: OrderIntent,
    ) -> ExecutionClaim:
        self.claims.append(intent.action)
        return ExecutionClaim(
            acquired=self.acquired,
            idempotency_key="cbr_auto:v1:key",
            claim_id=41 if intent.action == "YES" else 42,
            existing_status=None if self.acquired else "EXECUTED",
            existing_order_id=None if self.acquired else "old-order",
        )

    def complete(self, **kwargs: object) -> None:
        self.completions.append(dict(kwargs))

    def close(self) -> None:
        self.closed = True


class _Client:
    wallet = WALLET
    wallet_type = "GNOSIS_SAFE"

    def __init__(self):
        self.order_creations: list[dict] = []
        self.batch_posts: list[list[object]] = []
        self.closed = False

    def get_balance_allowance(self, *, asset_type: str) -> object:
        return SimpleNamespace(balance="50000000")

    def create_limit_order(self, **kwargs: object) -> object:
        self.order_creations.append(dict(kwargs))
        return SimpleNamespace(
            token_id=kwargs["token_id"],
            order_type="GTC",
            post_only=kwargs["post_only"],
            price=kwargs["price"],
            size=kwargs["size"],
        )

    def post_orders(
        self,
        signed_orders: list[object],
    ) -> tuple[object, ...]:
        self.batch_posts.append(list(signed_orders))
        return tuple(
            SimpleNamespace(
                ok=True,
                order_id=f"order-{index + 1}",
                status="LIVE",
            )
            for index, _ in enumerate(signed_orders)
        )

    def close(self) -> None:
        self.closed = True


class WarmLiveOrderExecutorTests(unittest.TestCase):
    def _executor(
        self,
        *,
        client: _Client,
        ledger: _Ledger,
        safety: LiveSafetySettings | None = None,
    ) -> tuple[
        WarmLiveOrderExecutor,
        _AccountRepository,
    ]:
        repository = _AccountRepository()
        executor = WarmLiveOrderExecutor(
            subscriptions=[_subscription()],
            database_url="postgresql://unused",
            safety=safety or _safety(),
            account_repository=repository,
            market_gateway=_MarketGateway(),
            ledger=ledger,
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, key: "private-key",
        )
        return executor, repository

    def test_prepare_warms_once_then_places_ordinary_gtc(self) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, repository = self._executor(
            client=client,
            ledger=ledger,
        )

        summary = executor.prepare()
        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]
        executor.close()

        self.assertEqual(summary.rule_count, 1)
        self.assertEqual(summary.account_count, 1)
        self.assertEqual(summary.outcome_count, 2)
        self.assertEqual(summary.maximum_notional, Decimal("20.0"))
        self.assertEqual(repository.loads, 1)
        self.assertEqual(ledger.ready_checks, 1)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "LIVE")
        self.assertEqual(result.order_id, "order-1")
        self.assertEqual(
            client.order_creations,
            [
                {
                    "token_id": "token-yes",
                    "price": "0.2",
                    "size": "100",
                    "side": "BUY",
                    "post_only": False,
                },
                {
                    "token_id": "token-no",
                    "price": "0.2",
                    "size": "100",
                    "side": "BUY",
                    "post_only": False,
                },
            ],
        )
        self.assertEqual(len(client.batch_posts), 1)
        self.assertEqual(
            [order.token_id for order in client.batch_posts[0]],
            ["token-yes"],
        )
        self.assertEqual(
            ledger.completions[0]["status"],
            "EXECUTED",
        )
        self.assertTrue(client.closed)
        self.assertTrue(repository.closed)
        self.assertTrue(ledger.closed)

    def test_duplicate_never_reaches_order_submission(self) -> None:
        client = _Client()
        ledger = _Ledger(acquired=False)
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare()

        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertEqual(result.status, "DUPLICATE_SKIPPED")
        self.assertEqual(result.order_id, "old-order")
        self.assertFalse(result.attempted)
        self.assertEqual(client.batch_posts, [])

    def test_execute_posts_presigned_order_without_book_refresh(
        self,
    ) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare()

        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertEqual(result.status, "LIVE")
        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertFalse(client.batch_posts[0][0].post_only)
        self.assertEqual(ledger.completions[0]["status"], "EXECUTED")

    def test_multiple_claimed_orders_use_one_batch_post(self) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare()

        results = executor.execute(
            [_intent(action="YES"), _intent(action="NO")],
            release=_release(),
        )

        self.assertEqual([result.status for result in results], ["LIVE", "LIVE"])
        self.assertCountEqual(ledger.claims, ["YES", "NO"])
        self.assertEqual(len(client.batch_posts), 1)
        self.assertEqual(
            [order.token_id for order in client.batch_posts[0]],
            ["token-yes", "token-no"],
        )

    def test_aggregate_notional_cap_fails_closed(self) -> None:
        client = _Client()
        ledger = _Ledger()
        safety = LiveSafetySettings(
            trading_enabled=True,
            post_only=False,
            allowed_account="kinderSman",
            max_order_quantity=Decimal("100"),
            max_notional=Decimal("20"),
            max_total_notional=Decimal("19"),
            accounts_master_key="test-master-key",
        )
        executor, _ = self._executor(
            client=client,
            ledger=ledger,
            safety=safety,
        )

        with self.assertRaisesRegex(
            Exception,
            "aggregate notional cap",
        ):
            executor.prepare()

    def test_unavailable_executor_reports_reason(self) -> None:
        executor = UnavailableLiveOrderExecutor("database offline")

        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertEqual(result.status, "SKIPPED")
        self.assertIn("database offline", result.error or "")


if __name__ == "__main__":
    unittest.main()
