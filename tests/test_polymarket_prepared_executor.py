from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import (
    ExecutionStatus,
    OrderSide,
    OrderTemplate,
    Outcome,
    ResolutionSignal,
)
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
        self.reserve_calls: list[dict] = []
        self.completions: list[dict] = []
        self.cleanups: list[dict] = []

    def ensure_ready(self) -> None:
        return None

    def reserve_many(self, *, context, templates, effective_prices):
        template_rows = tuple(templates)
        self.reserve_calls.append(
            {
                "context": context,
                "templates": template_rows,
                "effective_prices": effective_prices,
            }
        )
        if self.reserve_error is not None:
            raise self.reserve_error
        return tuple(
            ResolutionExecutionClaim(
                claim_id=index + 1,
                idempotency_key=f"claim-{index + 1}",
                scope_id=context.scope_id,
                template_id=template.template_id,
            )
            for index, template in enumerate(template_rows)
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
        self.hot_path = False

    def get_balance_allowance(self, *, asset_type: str):
        if self.hot_path:
            raise AssertionError(
                "balance lookup is forbidden after the signal"
            )
        return SimpleNamespace(balance="100000000")

    def get_order_book(self, *, token_id: str):
        if self.hot_path:
            raise AssertionError(
                "book lookup is forbidden after the signal"
            )
        return SimpleNamespace(
            condition_id=CONDITION_ID,
            tick_size="0.001",
            min_order_size="5",
            asks=(),
        )

    def create_limit_order(self, **kwargs: object):
        if self.hot_path:
            raise AssertionError(
                "order signing is forbidden after the signal"
            )
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
        return tuple(
            SimpleNamespace(
                ok=True,
                order_id=f"order-{index + 1}",
                status="LIVE",
            )
            for index, _order in enumerate(rows)
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
    def test_conflicting_outcomes_fail_before_batch_submission(self) -> None:
        ledger = _Ledger()
        client = _Client()
        signal = ResolutionSignal(
            signal_id="fed:test:conflict",
            source="fed_fomc",
            subject="central_bank:FED:policy_rate:test",
            metric="central_bank.policy_rate.change_bps",
            value=Decimal("0"),
            detected_at=datetime.now(timezone.utc),
        )
        context = PreparationContext(
            scope_id=signal.signal_id,
            source=signal.source,
            source_reference="https://www.federalreserve.gov/",
        )
        templates = tuple(
            OrderTemplate(
                template_id=f"fed:conflict:{outcome.value}",
                strategy_id="numeric_threshold",
                account_name="KinderSman",
                condition_id=CONDITION_ID,
                outcome=outcome,
                side=OrderSide.BUY,
                desired_price=Decimal("0.9"),
                quantity=Decimal("5"),
                metadata={"production_scope_id": "fed:scope:conflict"},
            )
            for outcome in (Outcome.YES, Outcome.NO)
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

        preparation = executor.prepare(templates, context=context)
        client.hot_path = True
        results = executor.execute(
            tuple(
                template.bind(signal_id=signal.signal_id)
                for template in templates
            ),
            signal=signal,
        )

        self.assertTrue(preparation.ready)
        self.assertEqual(client.posts, [])
        self.assertEqual(ledger.reserve_calls, [])
        self.assertTrue(
            all(
                result.status is ExecutionStatus.SKIPPED
                and result.error
                == "polymarket_selection_group_conflict"
                for result in results
            )
        )
        executor.close()

    def test_five_selected_profiles_use_one_client_batch(self) -> None:
        ledger = _Ledger()
        client = _Client()
        signal = ResolutionSignal(
            signal_id="fed:test:execution_batch",
            source="fed_fomc",
            subject="central_bank:FED:policy_rate:test",
            metric="central_bank.policy_rate.change_bps",
            value=Decimal("0"),
            detected_at=datetime.now(timezone.utc),
        )
        context = PreparationContext(
            scope_id=signal.signal_id,
            source=signal.source,
            source_reference="https://www.federalreserve.gov/",
        )
        templates = tuple(
            OrderTemplate(
                template_id=f"fed:{index}:YES",
                strategy_id="numeric_threshold",
                account_name="KinderSman",
                condition_id=CONDITION_ID,
                outcome=Outcome.YES,
                side=OrderSide.BUY,
                desired_price=Decimal("0.9"),
                quantity=Decimal("5"),
                metadata={
                    "production_scope_id": f"fed:scope:{index}",
                },
            )
            for index in range(5)
        )
        executor = PolymarketPreparedExecutor(
            database_url="postgresql://unused",
            safety=replace(
                _safety(),
                max_total_notional=Decimal("22.5"),
            ),
            account_repository=_AccountRepository(),
            market_gateway=_MarketGateway(),
            ledger=ledger,
            client_factory=lambda private_key, wallet: client,
            decryptor=lambda encrypted, key: "private-key",
        )

        preparation = executor.prepare(templates, context=context)
        client.hot_path = True
        results = executor.execute(
            tuple(
                template.bind(signal_id=signal.signal_id)
                for template in templates
            ),
            signal=signal,
        )

        self.assertTrue(preparation.ready)
        self.assertEqual(executor.maximum_notional, Decimal("22.5"))
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(len(client.posts[0]), 5)
        self.assertEqual(len(ledger.reserve_calls), 1)
        self.assertEqual(len(ledger.completions), 5)
        self.assertTrue(
            all(
                result.status is ExecutionStatus.SUBMITTED
                for result in results
            )
        )
        executor.close()

    def test_preparation_window_expiry_has_no_claims_to_close(
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
        self.assertEqual(len(executor.details), 1)
        self.assertEqual(ledger.reserve_calls, [])
        self.assertEqual(ledger.completions, [])

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
        self.assertEqual(len(ledger.reserve_calls), 1)
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

    def test_duplicate_claim_blocks_before_order_submission(self) -> None:
        ledger = _Ledger(
            reserve_error=RuntimeError("duplicate")
        )
        client = _Client()
        _executor, coordinator, preparation, outcome = _run(
            ledger=ledger,
            client=client,
        )
        coordinator.close()

        self.assertTrue(preparation.ready)
        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        self.assertEqual(
            outcome.order_results[0].status,
            ExecutionStatus.SKIPPED,
        )
        self.assertFalse(outcome.order_results[0].attempted)
        self.assertEqual(client.posts, [])

    def test_restart_before_signal_does_not_leave_execution_claims(
        self,
    ) -> None:
        ledger = _Ledger()
        first_client = _Client()
        _executor, first, preparation, _outcome = _run(
            ledger=ledger,
            client=first_client,
            poll=False,
        )
        first.close()

        second_client = _Client()
        _executor, second, repeated, _outcome = _run(
            ledger=ledger,
            client=second_client,
            poll=False,
        )
        second.close()

        self.assertTrue(preparation.ready)
        self.assertTrue(repeated.ready)
        self.assertEqual(ledger.reserve_calls, [])
        self.assertEqual(ledger.completions, [])
        self.assertEqual(first_client.posts, [])
        self.assertEqual(second_client.posts, [])

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
