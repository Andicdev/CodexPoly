from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import (
    ExecutionStatus,
    ResolutionSignal,
)
from cbr_trading.execution import (
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.sources import ManualResolutionSource
from cbr_trading.strategies import FixedOutcomeStrategy


def _rule() -> dict:
    return {
        "id": 103,
        "type": "resolution_market",
        "ticker": "ANTHROPIC",
        "rule_key": "opus_yes",
        "account_name": "KinderSman",
        "condition_id": "0x" + ("7" * 64),
        "order_qty": 100,
        "order_price": 0.9,
        "params": {
            "source": "anthropic_official",
            "subject": "next_claude_opus",
            "metric": "public_release",
            "decision_mode": "fixed_outcome",
            "signal_value": True,
            "action": "YES",
            "order_price_yes": 0.9,
            "order_lifecycle": {"kind": "keep_open"},
        },
    }


def _safety(
    *,
    max_notional: str = "100",
) -> LiveSafetySettings:
    return LiveSafetySettings(
        trading_enabled=False,
        post_only=True,
        allowed_account="KinderSman",
        max_order_quantity=Decimal("200"),
        max_notional=Decimal(max_notional),
        max_total_notional=Decimal("100"),
        accounts_master_key="present",
    )


class _AccountRepository:
    def __init__(self):
        self.closed = False

    def load_active(self, name: str) -> TradingAccountRecord:
        return TradingAccountRecord(
            name=name,
            wallet_address="0x1234567890abcdef",
            venue="polymarket_clob",
            is_active=True,
            signature_type=1,
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


class _LiveExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    def check_authenticated(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(order_presigned=True)


class PolymarketPreflightPreparedExecutorTests(unittest.TestCase):
    def test_runs_source_strategy_preflight_without_submission(
        self,
    ) -> None:
        rule = _rule()
        strategy = FixedOutcomeStrategy((rule,))
        signal = ResolutionSignal(
            signal_id="manual-preflight:rule:103",
            source="anthropic_official",
            subject="next_claude_opus",
            metric="public_release",
            value=True,
            detected_at=datetime.now(timezone.utc),
        )
        source = ManualResolutionSource(
            source_name=signal.source,
            signals=(signal,),
        )
        context = PreparationContext(
            scope_id=signal.signal_id,
            source=signal.source,
            source_reference="manual://resolution-rule/103",
        )
        accounts = _AccountRepository()
        live = _LiveExecutor()
        executor = PolymarketPreflightPreparedExecutor(
            database_url="postgresql://unused",
            safety=_safety(),
            account_repository=accounts,
            market_gateway=_MarketGateway(),
            live_executor=live,
        )
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=context,
        )

        preparation = coordinator.prepare()
        outcome = coordinator.poll_once()
        coordinator.close()

        self.assertTrue(preparation.ready)
        self.assertEqual(len(executor.details), 1)
        self.assertEqual(executor.maximum_notional, Decimal("90.0"))
        self.assertTrue(executor.details[0].order_presigned)
        self.assertEqual(executor.details[0].outcome, "YES")
        self.assertEqual(
            outcome.status,
            CoordinationStatus.COMPLETED,
        )
        self.assertEqual(len(outcome.intents), 1)
        self.assertEqual(
            outcome.order_results[0].status,
            ExecutionStatus.DRY_RUN,
        )
        self.assertFalse(outcome.order_results[0].attempted)
        self.assertEqual(len(live.calls), 1)
        self.assertTrue(live.calls[0]["presign"])
        self.assertTrue(
            live.calls[0]["settings"].trading_enabled
        )
        self.assertTrue(accounts.closed)

    def test_notional_cap_blocks_before_authenticated_check(
        self,
    ) -> None:
        strategy = FixedOutcomeStrategy((_rule(),))
        accounts = _AccountRepository()
        live = _LiveExecutor()
        executor = PolymarketPreflightPreparedExecutor(
            database_url="postgresql://unused",
            safety=_safety(max_notional="50"),
            account_repository=accounts,
            market_gateway=_MarketGateway(),
            live_executor=live,
        )
        context = PreparationContext(
            scope_id="manual-preflight:rule:103",
            source="anthropic_official",
            source_reference="manual://resolution-rule/103",
        )

        summary = executor.prepare(
            strategy.order_templates(),
            context=context,
        )
        executor.close()

        self.assertFalse(summary.ready)
        self.assertIn("max_notional_exceeded", summary.items[0].error)
        self.assertEqual(live.calls, [])


if __name__ == "__main__":
    unittest.main()
