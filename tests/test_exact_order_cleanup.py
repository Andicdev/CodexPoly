from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import OrderSide
from cbr_trading.execution import (
    CancellationResult,
    OrderInspectionResult,
    RemoteOrderSnapshot,
    RemoteOrderState,
)
from cbr_trading.live.exact_cleanup import cleanup_exact_order
from cbr_trading.live.safety import LiveSafetySettings


def _inspection(
    state: RemoteOrderState,
) -> OrderInspectionResult:
    matched = (
        Decimal("5")
        if state == RemoteOrderState.FILLED
        else Decimal("0")
    )
    return OrderInspectionResult(
        requested_order_ids=("order-1",),
        snapshots=(
            RemoteOrderSnapshot(
                order_id="order-1",
                condition_id="condition-1",
                asset_id="asset-1",
                side=OrderSide.BUY,
                limit_price=Decimal("0.9"),
                original_quantity=Decimal("5"),
                matched_quantity=matched,
                state=state,
                remote_status=state.value,
                observed_at=datetime.now(timezone.utc),
            ),
        ),
    )


class _Gateway:
    def __init__(self, states):
        self.states = list(states)
        self.cancel_calls = []
        self.closed = False

    def inspect_orders(self, *, account_name: str, order_ids):
        return _inspection(self.states.pop(0))

    def cancel_orders(self, *, account_name: str, order_ids):
        normalized = tuple(order_ids)
        self.cancel_calls.append(normalized)
        return CancellationResult(
            requested_order_ids=normalized,
            cancelled_order_ids=normalized,
        )

    def close(self):
        self.closed = True


class ExactOrderCleanupTests(unittest.TestCase):
    def test_cancels_only_exact_id_and_confirms_terminal(self) -> None:
        gateway = _Gateway(
            [RemoteOrderState.OPEN, RemoteOrderState.CANCELLED]
        )

        result = cleanup_exact_order(
            database_url="postgresql://unused",
            safety=LiveSafetySettings(),
            account_name="KinderSman",
            order_id="order-1",
            gateway_factory=lambda **kwargs: gateway,
        )

        self.assertEqual(gateway.cancel_calls, [("order-1",)])
        self.assertTrue(result["confirmed_terminal"])
        self.assertEqual(result["final_state"], "CANCELLED")
        self.assertTrue(gateway.closed)

    def test_immediate_fill_never_requests_cancellation(self) -> None:
        gateway = _Gateway([RemoteOrderState.FILLED])

        result = cleanup_exact_order(
            database_url="postgresql://unused",
            safety=LiveSafetySettings(),
            account_name="KinderSman",
            order_id="order-1",
            gateway_factory=lambda **kwargs: gateway,
        )

        self.assertEqual(gateway.cancel_calls, [])
        self.assertFalse(result["cancel_requested"])
        self.assertEqual(result["final_state"], "FILLED")


if __name__ == "__main__":
    unittest.main()
