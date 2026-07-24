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


def _reprice_subscription() -> dict:
    subscription = _subscription()
    subscription["params"] = {
        **subscription["params"],
        "order_price_yes": "0.999",
        "order_price_no": "0.95",
        "order_lifecycle": {
            "kind": "reprice_on_tick_change",
            "old_tick": "0.01",
            "new_tick": "0.001",
        },
    }
    return subscription


def _intent(
    *,
    action: str = "YES",
    limit_price: Decimal | float = 0.20,
) -> OrderIntent:
    return OrderIntent(
        rule_id=98,
        rule_key="cbr_decrease_fast",
        account_name="KinderSman",
        condition_id=CONDITION_ID,
        action=action,
        quantity=100,
        limit_price=limit_price,
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
    def __init__(self, *, tick_size: Decimal = Decimal("0.01")):
        self.tick_size = tick_size

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
            tick_size=self.tick_size,
            minimum_order_size=Decimal("5"),
            neg_risk=False,
        )


class _Ledger:
    def __init__(
        self,
        *,
        reservation_error: Exception | None = None,
        events: list[str] | None = None,
    ):
        self.reservation_error = reservation_error
        self.events = events
        self.ready_checks = 0
        self.claims: list[str] = []
        self.completions: list[dict] = []
        self.closed = False

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def reserve_many(
        self,
        *,
        release_url: str,
        intents: tuple[OrderIntent, ...],
    ) -> tuple[ExecutionClaim, ...]:
        if self.reservation_error is not None:
            raise self.reservation_error
        if self.events is not None:
            self.events.append("reserve")
        self.claims.extend(intent.action for intent in intents)
        return tuple(
            ExecutionClaim(
                acquired=True,
                idempotency_key=f"cbr_auto:v1:{index}",
                claim_id=41 + index,
            )
            for index, _ in enumerate(intents)
        )

    def complete(self, **kwargs: object) -> None:
        if self.events is not None:
            self.events.append("complete")
        self.completions.append(dict(kwargs))

    def close(self) -> None:
        self.closed = True


class _Client:
    wallet = WALLET
    wallet_type = "GNOSIS_SAFE"

    def __init__(
        self,
        *,
        events: list[str] | None = None,
        balance: str = "50000000",
    ):
        self.events = events
        self.balance = balance
        self.order_creations: list[dict] = []
        self.batch_posts: list[list[object]] = []
        self.closed = False

    def get_balance_allowance(self, *, asset_type: str) -> object:
        return SimpleNamespace(balance=self.balance)

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
        if self.events is not None:
            self.events.append("post")
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
        subscription: dict | None = None,
        market_gateway: _MarketGateway | None = None,
    ) -> tuple[
        WarmLiveOrderExecutor,
        _AccountRepository,
    ]:
        repository = _AccountRepository()
        executor = WarmLiveOrderExecutor(
            subscriptions=[subscription or _subscription()],
            database_url="postgresql://unused",
            safety=safety or _safety(),
            account_repository=repository,
            market_gateway=market_gateway or _MarketGateway(),
            ledger=ledger,
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, key: "private-key",
        )
        return executor, repository

    @staticmethod
    def _high_price_safety() -> LiveSafetySettings:
        return LiveSafetySettings(
            trading_enabled=True,
            post_only=False,
            allowed_account="kinderSman",
            max_order_quantity=Decimal("100"),
            max_notional=Decimal("100"),
            max_total_notional=Decimal("100"),
            accounts_master_key="test-master-key",
        )

    def test_prepare_warms_once_then_places_ordinary_gtc(self) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, repository = self._executor(
            client=client,
            ledger=ledger,
        )

        summary = executor.prepare(release_url=_release().url)
        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]
        executor.close()

        self.assertEqual(summary.rule_count, 1)
        self.assertEqual(summary.account_count, 1)
        self.assertEqual(summary.outcome_count, 2)
        self.assertEqual(summary.maximum_notional, Decimal("20.0"))
        self.assertEqual(len(summary.prepared_orders), 2)
        self.assertEqual(
            {item.token_id for item in summary.prepared_orders},
            {"token-yes", "token-no"},
        )
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

    def test_reprice_policy_preserves_desired_price_and_signs_current_tick(
        self,
    ) -> None:
        client = _Client(balance="500000000")
        ledger = _Ledger()
        executor, _ = self._executor(
            client=client,
            ledger=ledger,
            safety=self._high_price_safety(),
            subscription=_reprice_subscription(),
        )

        summary = executor.prepare(release_url=_release().url)
        yes = next(
            item
            for item in summary.prepared_orders
            if item.outcome == "YES"
        )
        result = executor.execute(
            [_intent(limit_price=Decimal("0.99"))],
            release=_release(),
        )[0]

        self.assertEqual(yes.desired_price, Decimal("0.999"))
        self.assertEqual(yes.limit_price, Decimal("0.99"))
        self.assertEqual(yes.tick_size, Decimal("0.01"))
        self.assertEqual(
            [row["price"] for row in client.order_creations],
            ["0.99", "0.95"],
        )
        self.assertTrue(result.success)

    def test_reprice_policy_uses_desired_price_when_fine_tick_is_active(
        self,
    ) -> None:
        client = _Client(balance="500000000")
        executor, _ = self._executor(
            client=client,
            ledger=_Ledger(),
            safety=self._high_price_safety(),
            subscription=_reprice_subscription(),
            market_gateway=_MarketGateway(
                tick_size=Decimal("0.001")
            ),
        )

        summary = executor.prepare(release_url=_release().url)
        yes = next(
            item
            for item in summary.prepared_orders
            if item.outcome == "YES"
        )

        self.assertEqual(yes.desired_price, Decimal("0.999"))
        self.assertEqual(yes.limit_price, Decimal("0.999"))
        self.assertEqual(yes.tick_size, Decimal("0.001"))

    def test_keep_open_price_must_still_align_to_current_tick(self) -> None:
        client = _Client()
        subscription = _subscription()
        subscription["order_price"] = "0.999"
        executor, _ = self._executor(
            client=client,
            ledger=_Ledger(),
            safety=self._high_price_safety(),
            subscription=subscription,
        )

        with self.assertRaisesRegex(
            Exception,
            "limit_price_not_tick_aligned",
        ):
            executor.prepare(release_url=_release().url)

        self.assertEqual(client.order_creations, [])

    def test_reprice_policy_rejects_unexpected_market_tick(self) -> None:
        client = _Client()
        executor, _ = self._executor(
            client=client,
            ledger=_Ledger(),
            safety=self._high_price_safety(),
            subscription=_reprice_subscription(),
            market_gateway=_MarketGateway(
                tick_size=Decimal("0.1")
            ),
        )

        with self.assertRaisesRegex(
            Exception,
            "unexpected_tick_size_for_reprice_policy",
        ):
            executor.prepare(release_url=_release().url)

        self.assertEqual(client.order_creations, [])

    def test_duplicate_reservation_fails_before_polling(self) -> None:
        client = _Client()
        ledger = _Ledger(
            reservation_error=RuntimeError(
                "reservation already exists"
            )
        )
        executor, _ = self._executor(client=client, ledger=ledger)

        with self.assertRaisesRegex(
            Exception,
            "Failed to reserve all live orders before polling",
        ):
            executor.prepare(release_url=_release().url)
        self.assertEqual(client.batch_posts, [])

    def test_execute_posts_presigned_order_without_book_refresh(
        self,
    ) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare(release_url=_release().url)

        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertEqual(result.status, "LIVE")
        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertFalse(client.batch_posts[0][0].post_only)
        self.assertEqual(ledger.completions[0]["status"], "EXECUTED")

    def test_execute_has_no_database_call_before_batch_post(self) -> None:
        events: list[str] = []
        client = _Client(events=events)
        ledger = _Ledger(events=events)
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare(release_url=_release().url)

        events.clear()
        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertTrue(result.success)
        self.assertEqual(events[0], "post")
        self.assertEqual(
            events,
            ["post", "complete", "complete"],
        )

    def test_multiple_claimed_orders_use_one_batch_post(self) -> None:
        client = _Client()
        ledger = _Ledger()
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare(release_url=_release().url)

        results = executor.execute(
            [_intent(action="YES"), _intent(action="NO")],
            release=_release(),
        )

        self.assertEqual([result.status for result in results], ["LIVE", "LIVE"])
        self.assertEqual(ledger.claims, ["YES", "NO"])
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
            executor.prepare(release_url=_release().url)

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
