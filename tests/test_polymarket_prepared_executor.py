from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import ExecutionStatus, ResolutionSignal
from cbr_trading.execution import (
    PolymarketPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.resolution_idempotency import (
    ResolutionExecutionClaim,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.sources import ManualResolutionSource
from cbr_trading.strategies import FixedOutcomeStrategy


CONDITION_ID = "0x" + ("7" * 64)
WALLET = "0x" + ("8" * 40)


def _rule() -> dict:
    return {
        "id": 103,
        "type": "resolution_market",
        "ticker": "ANTHROPIC",
        "rule_key": "opus_yes",
        "account_name": "KinderSman",
        "condition_id": CONDITION_ID,
        "order_qty": "5",
        "order_price": "0.9",
        "params": {
            "source": "anthropic_official",
            "subject": "next_claude_opus",
            "metric": "public_release",
            "decision_mode": "fixed_outcome",
            "signal_value": True,
            "action": "YES",
            "order_price_yes": "0.9",
            "order_lifecycle": {"kind": "keep_open"},
        },
    }


def _safety() -> LiveSafetySettings:
    return LiveSafetySettings(
        trading_enabled=True,
        post_only=True,
        allowed_account="KinderSman",
        max_order_quantity=Decimal("5"),
        max_notional=Decimal("4.5"),
        max_total_notional=Decimal("4.5"),
        accounts_master_key="test-master-key",
    )


class _AccountRepository:
    def load_active(self, name: str) -> TradingAccountRecord:
        return TradingAccountRecord(
            name=name,
            wallet_address=WALLET,
            venue="polymarket_clob",
            is_active=True,
            signature_type=2,
            encrypted_private_key=b"encrypted",
        )

    def close(self) -> None:
        return None


class _MarketGateway:
    def load_snapshot(self, *, condition_id: str, outcome: str):
        return MarketSnapshot(
            condition_id=condition_id,
            question="Claude Opus by July 24?",
            outcome=outcome,
            token_id="yes-token",
            best_bid=Decimal("0.999"),
            best_ask=None,
            last_trade_price=Decimal("0.999"),
            tick_size=Decimal("0.001"),
            minimum_order_size=Decimal("5"),
            neg_risk=False,
        )


class _Ledger:
    def __init__(
        self,
        *,
        reserve_error: Exception | None = None,
        complete_error: Exception | None = None,
    ):
        self.reserve_error = reserve_error
        self.complete_error = complete_error
        self.completions: list[dict] = []
        self.cleanups: list[dict] = []

    def ensure_ready(self) -> None:
        return None

    def reserve_many(self, *, context, templates, effective_prices):
        if self.reserve_error is not None:
            raise self.reserve_error
        return tuple(
            ResolutionExecutionClaim(
                claim_id=index + 1,
                idempotency_key=f"claim-{index + 1}",
                scope_id=context.scope_id,
                template_id=template.template_id,
            )
            for index, template in enumerate(templates)
        )

    def complete(self, claim_id: int, **kwargs: object) -> None:
        if self.complete_error is not None:
            raise self.complete_error
        self.completions.append(
            {"claim_id": claim_id, **kwargs}
        )

    def record_cleanup(self, claim_id: int, *, cleanup) -> None:
        self.cleanups.append(
            {"claim_id": claim_id, "cleanup": cleanup}
        )

    def close(self) -> None:
        return None


class _Client:
    wallet = WALLET
    wallet_type = "GNOSIS_SAFE"

    def __init__(
        self,
        *,
        post_error: Exception | None = None,
    ):
        self.post_error = post_error
        self.posts: list[tuple] = []
        self.closed = False

    def get_balance_allowance(self, *, asset_type: str):
        return SimpleNamespace(balance="100000000")

    def get_order_book(self, *, token_id: str):
        return SimpleNamespace(
            condition_id=CONDITION_ID,
            tick_size="0.001",
            min_order_size="5",
            asks=(),
        )

    def create_limit_order(self, **kwargs: object):
        return SimpleNamespace(
            token_id=kwargs["token_id"],
            order_type="GTC",
            post_only=kwargs["post_only"],
        )

    def post_orders(self, orders):
        rows = tuple(orders)
        self.posts.append(rows)
        if self.post_error is not None:
            raise self.post_error
        return (
            SimpleNamespace(
                ok=True,
                order_id="order-1",
                status="LIVE",
            ),
        )

    def close(self) -> None:
        self.closed = True


def _run(
    *,
    ledger: _Ledger,
    client: _Client,
    poll: bool = True,
):
    strategy = FixedOutcomeStrategy((_rule(),))
    signal = ResolutionSignal(
        signal_id="manual-live-test:run-1:rule:103",
        source="anthropic_official",
        subject="next_claude_opus",
        metric="public_release",
        value=True,
        detected_at=datetime.now(timezone.utc),
    )
    context = PreparationContext(
        scope_id=signal.signal_id,
        source=signal.source,
        source_reference="manual://resolution-live-test/run-1",
    )
    executor = PolymarketPreparedExecutor(
        database_url="postgresql://unused",
        safety=_safety(),
        account_repository=_AccountRepository(),
        market_gateway=_MarketGateway(),
        ledger=ledger,
        client_factory=lambda private_key, wallet: client,
        decryptor=lambda encrypted, key: "private-key",
    )
    coordinator = ResolutionTradingCoordinator(
        source=ManualResolutionSource(
            source_name=signal.source,
            signals=(signal,),
        ),
        strategies=(strategy,),
        executor=executor,
        context=context,
    )
    preparation = coordinator.prepare()
    outcome = (
        coordinator.poll_once()
        if preparation.ready and poll
        else None
    )
    return executor, coordinator, preparation, outcome


class PolymarketPreparedExecutorTests(unittest.TestCase):
    def test_explicit_window_expiry_closes_all_pending_claims(
        self,
    ) -> None:
        ledger = _Ledger()
        client = _Client()
        executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
            poll=False,
        )

        executor.expire_pending()
        coordinator.close()

        self.assertTrue(preparation.ready)
        self.assertIsNone(outcome)
        self.assertEqual(client.posts, [])
        self.assertEqual(
            len(ledger.completions),
            len(executor.details),
        )
        self.assertTrue(
            all(
                completion["status"] == "EXPIRED"
                for completion in ledger.completions
            )
        )
        self.assertTrue(
            all(
                completion["result"]["reason"]
                == "preparation_window_expired"
                for completion in ledger.completions
            )
        )

    def test_submits_selected_template_and_completes_claim(self) -> None:
        ledger = _Ledger()
        client = _Client()
        executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
        )
        coordinator.close()

        self.assertTrue(preparation.ready)
        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        result = outcome.order_results[0]
        self.assertEqual(result.status, ExecutionStatus.SUBMITTED)
        self.assertEqual(result.orders[0].order_id, "order-1")
        self.assertEqual(result.handle.live_order_ids, ("order-1",))
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(
            ledger.completions[0]["status"],
            "EXECUTED",
        )
        self.assertEqual(
            executor.claim_id_for_template(
                "fixed-outcome-rule:103:YES"
            ),
            1,
        )
        self.assertTrue(client.closed)

    def test_duplicate_claim_blocks_before_source_polling(self) -> None:
        ledger = _Ledger(
            reserve_error=RuntimeError("duplicate")
        )
        client = _Client()
        _executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
        )
        coordinator.close()

        self.assertFalse(preparation.ready)
        self.assertIsNone(outcome)
        self.assertEqual(client.posts, [])

    def test_submission_exception_is_ambiguous_and_audited(self) -> None:
        ledger = _Ledger()
        client = _Client(
            post_error=TimeoutError(
                "postgresql://user:password@db.example/app"
            )
        )
        _executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
        )
        coordinator.close()

        self.assertTrue(preparation.ready)
        result = outcome.order_results[0]
        self.assertEqual(result.status, ExecutionStatus.AMBIGUOUS)
        self.assertTrue(result.attempted)
        self.assertEqual(
            ledger.completions[0]["status"],
            "ERROR",
        )
        self.assertNotIn("password", result.error)

    def test_accepted_order_with_ledger_failure_stays_owned(self) -> None:
        ledger = _Ledger(
            complete_error=RuntimeError("database unavailable")
        )
        client = _Client()
        _executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
        )
        coordinator.close()

        self.assertTrue(preparation.ready)
        result = outcome.order_results[0]
        self.assertEqual(result.status, ExecutionStatus.AMBIGUOUS)
        self.assertEqual(result.orders[0].order_id, "order-1")
        self.assertEqual(result.handle.live_order_ids, ("order-1",))
        self.assertIn("ledger completion failed", result.error)


if __name__ == "__main__":
    unittest.main()
