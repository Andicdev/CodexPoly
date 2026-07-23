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
        post_only=True,
        allowed_account="kinderSman",
        max_order_quantity=Decimal("100"),
        max_notional=Decimal("20"),
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
        return ExecutionClaim(
            acquired=self.acquired,
            idempotency_key="cbr_auto:v1:key",
            claim_id=41,
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

    def __init__(self, *, fresh_ask: str = "0.60"):
        self.fresh_ask = fresh_ask
        self.placements: list[dict] = []
        self.closed = False

    def get_balance_allowance(self, *, asset_type: str) -> object:
        return SimpleNamespace(balance="50000000")

    def get_order_book(self, *, token_id: str) -> object:
        level = lambda price: SimpleNamespace(price=price)
        return SimpleNamespace(
            condition_id=CONDITION_ID,
            bids=[level("0.10")],
            asks=[level(self.fresh_ask)],
            last_trade_price="0.30",
            tick_size="0.01",
            min_order_size="5",
            neg_risk=False,
        )

    def place_limit_order(self, **kwargs: object) -> object:
        self.placements.append(dict(kwargs))
        return SimpleNamespace(
            ok=True,
            order_id="order-123",
            status="LIVE",
        )

    def close(self) -> None:
        self.closed = True


class WarmLiveOrderExecutorTests(unittest.TestCase):
    def _executor(
        self,
        *,
        client: _Client,
        ledger: _Ledger,
    ) -> tuple[
        WarmLiveOrderExecutor,
        _AccountRepository,
    ]:
        repository = _AccountRepository()
        executor = WarmLiveOrderExecutor(
            subscriptions=[_subscription()],
            database_url="postgresql://unused",
            safety=_safety(),
            account_repository=repository,
            market_gateway=_MarketGateway(),
            ledger=ledger,
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, key: "private-key",
        )
        return executor, repository

    def test_prepare_warms_once_then_places_post_only(self) -> None:
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
        self.assertEqual(result.order_id, "order-123")
        self.assertEqual(
            client.placements,
            [
                {
                    "token_id": "token-yes",
                    "price": "0.2",
                    "size": "100",
                    "side": "BUY",
                    "post_only": True,
                }
            ],
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
        self.assertEqual(client.placements, [])

    def test_fresh_crossing_ask_fails_closed_after_claim(self) -> None:
        client = _Client(fresh_ask="0.20")
        ledger = _Ledger()
        executor, _ = self._executor(client=client, ledger=ledger)
        executor.prepare()

        result = executor.execute(
            [_intent()],
            release=_release(),
        )[0]

        self.assertEqual(result.status, "SKIPPED")
        self.assertFalse(result.attempted)
        self.assertIn("buy_would_cross_current_ask", result.error or "")
        self.assertEqual(client.placements, [])
        self.assertEqual(ledger.completions[0]["status"], "FAILED")

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
