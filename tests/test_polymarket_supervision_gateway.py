from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.domain import OrderSide, Outcome
from cbr_trading.execution import ReplacementOrderRequest
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionGatewayError,
    PolymarketSupervisionOrderGateway,
)


CONDITION_ID = "0x" + ("a" * 64)
WALLET = "0x" + ("b" * 40)


def _safety(
    **overrides,
) -> LiveSafetySettings:
    values = {
        "trading_enabled": True,
        "post_only": False,
        "allowed_account": "primary",
        "max_order_quantity": Decimal("100"),
        "max_notional": Decimal("100"),
        "max_total_notional": Decimal("100"),
        "accounts_master_key": "test-master-key",
    }
    values.update(overrides)
    return LiveSafetySettings(**values)


def _request(
    *,
    side: OrderSide = OrderSide.BUY,
    price: Decimal = Decimal("0.999"),
    tick_size: Decimal = Decimal("0.001"),
    quantity: Decimal | None = Decimal("25"),
    notional: Decimal | None = None,
) -> ReplacementOrderRequest:
    return ReplacementOrderRequest(
        order_group_id="group-1",
        account_name="primary",
        condition_id=CONDITION_ID,
        outcome=Outcome.YES,
        asset_id="asset-yes",
        side=side,
        limit_price=price,
        tick_size=tick_size,
        quantity=quantity,
        notional=notional,
        replaced_order_ids=("order-1",),
    )


def _book(
    *,
    condition_id: str = CONDITION_ID,
    token_id: str = "asset-yes",
    tick_size: Decimal = Decimal("0.001"),
    minimum_order_size: Decimal = Decimal("5"),
    bids: tuple[Decimal, ...] = (Decimal("0.40"),),
    asks: tuple[Decimal, ...] = (Decimal("0.60"),),
) -> object:
    return SimpleNamespace(
        condition_id=condition_id,
        token_id=token_id,
        tick_size=tick_size,
        min_order_size=minimum_order_size,
        bids=tuple(
            SimpleNamespace(price=price)
            for price in bids
        ),
        asks=tuple(
            SimpleNamespace(price=price)
            for price in asks
        ),
    )


class _AccountRepository:
    def __init__(self):
        self.loads: list[str] = []
        self.close_calls = 0

    def load_active(self, account_name: str) -> TradingAccountRecord:
        self.loads.append(account_name)
        return TradingAccountRecord(
            name="primary",
            wallet_address=WALLET,
            venue="polymarket_clob",
            is_active=True,
            signature_type=2,
            encrypted_private_key=b"encrypted",
        )

    def close(self) -> None:
        self.close_calls += 1


class _Client:
    wallet = WALLET
    wallet_type = "GNOSIS_SAFE"

    def __init__(self):
        self.cancel_response = SimpleNamespace(
            canceled=("order-1",),
            not_canceled={},
        )
        self.order_book = _book()
        self.place_response = SimpleNamespace(
            ok=True,
            order_id="order-2",
            status="live",
        )
        self.cancel_error: Exception | None = None
        self.book_error: Exception | None = None
        self.place_error: Exception | None = None
        self.cancel_calls: list[tuple[str, ...]] = []
        self.book_calls: list[str] = []
        self.place_calls: list[dict] = []
        self.close_calls = 0

    def cancel_orders(self, *, order_ids):
        self.cancel_calls.append(tuple(order_ids))
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.cancel_response

    def get_order_book(self, *, token_id):
        self.book_calls.append(token_id)
        if self.book_error is not None:
            raise self.book_error
        return self.order_book

    def place_limit_order(self, **kwargs):
        self.place_calls.append(dict(kwargs))
        if self.place_error is not None:
            raise self.place_error
        return self.place_response

    def close(self):
        self.close_calls += 1


class PolymarketSupervisionOrderGatewayTests(unittest.TestCase):
    def _gateway(
        self,
        *,
        client: _Client,
        safety: LiveSafetySettings | None = None,
    ) -> tuple[
        PolymarketSupervisionOrderGateway,
        _AccountRepository,
        list[tuple[str, str]],
    ]:
        repository = _AccountRepository()
        client_factory_calls: list[tuple[str, str]] = []

        def client_factory(
            private_key: str,
            wallet: str,
        ) -> _Client:
            client_factory_calls.append((private_key, wallet))
            return client

        gateway = PolymarketSupervisionOrderGateway(
            safety=safety or _safety(),
            account_repository=repository,
            client_factory=client_factory,
            decryptor=lambda encrypted, master_key: "private-key",
        )
        return gateway, repository, client_factory_calls

    def test_cancel_uses_one_exact_batch_and_normalizes_success(
        self,
    ) -> None:
        client = _Client()
        client.cancel_response = SimpleNamespace(
            canceled=("order-2", "order-1"),
            not_canceled={},
        )
        gateway, repository, factory_calls = self._gateway(
            client=client
        )

        result = gateway.cancel_orders(
            account_name="primary",
            order_ids=("order-1", "order-2"),
        )

        self.assertEqual(
            client.cancel_calls,
            [("order-1", "order-2")],
        )
        self.assertEqual(
            result.cancelled_order_ids,
            ("order-1", "order-2"),
        )
        self.assertEqual(result.failed_order_ids, ())
        self.assertEqual(repository.loads, ["primary"])
        self.assertEqual(
            factory_calls,
            [("private-key", WALLET)],
        )

    def test_partial_cancel_preserves_confirmed_external_effects(
        self,
    ) -> None:
        client = _Client()
        client.cancel_response = SimpleNamespace(
            canceled=("order-1",),
            not_canceled={"order-2": "order is not open"},
        )
        gateway, _, _ = self._gateway(client=client)

        result = gateway.cancel_orders(
            account_name="primary",
            order_ids=("order-1", "order-2"),
        )

        self.assertEqual(
            result.cancelled_order_ids,
            ("order-1",),
        )
        self.assertEqual(
            result.failed_order_ids,
            ("order-2",),
        )
        self.assertIn("order is not open", result.error)

    def test_cancel_response_cannot_expand_order_scope(self) -> None:
        client = _Client()
        client.cancel_response = SimpleNamespace(
            canceled=("order-1", "foreign-order"),
            not_canceled={},
        )
        gateway, _, _ = self._gateway(client=client)

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "expanded",
        ):
            gateway.cancel_orders(
                account_name="primary",
                order_ids=("order-1",),
            )

    def test_unauthorized_account_is_rejected_before_database_load(
        self,
    ) -> None:
        client = _Client()
        gateway, repository, factory_calls = self._gateway(
            client=client
        )

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "account_not_allowed",
        ):
            gateway.cancel_orders(
                account_name="another-account",
                order_ids=("order-1",),
            )

        self.assertEqual(repository.loads, [])
        self.assertEqual(factory_calls, [])
        self.assertEqual(client.cancel_calls, [])

    def test_place_refreshes_book_and_submits_valid_gtc(self) -> None:
        client = _Client()
        gateway, _, _ = self._gateway(client=client)

        orders = gateway.place_replacement(_request())

        self.assertEqual(client.book_calls, ["asset-yes"])
        self.assertEqual(
            client.place_calls,
            [
                {
                    "token_id": "asset-yes",
                    "price": "0.999",
                    "size": "25",
                    "side": "BUY",
                    "post_only": False,
                }
            ],
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].order_id, "order-2")
        self.assertEqual(orders[0].quantity, Decimal("25"))

    def test_notional_sizing_converts_to_share_quantity(self) -> None:
        client = _Client()
        client.order_book = _book(
            tick_size=Decimal("0.01"),
        )
        gateway, _, _ = self._gateway(client=client)

        orders = gateway.place_replacement(
            _request(
                price=Decimal("0.50"),
                tick_size=Decimal("0.01"),
                quantity=None,
                notional=Decimal("10"),
            )
        )

        self.assertEqual(
            client.place_calls[0]["size"],
            "20",
        )
        self.assertEqual(orders[0].quantity, Decimal("20"))

    def test_changed_book_tick_blocks_replacement(self) -> None:
        client = _Client()
        client.order_book = _book(
            tick_size=Decimal("0.01"),
        )
        gateway, _, _ = self._gateway(client=client)

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "tick does not match",
        ):
            gateway.place_replacement(_request())

        self.assertEqual(client.place_calls, [])

    def test_wrong_book_condition_blocks_replacement(self) -> None:
        client = _Client()
        client.order_book = _book(
            condition_id="another-condition",
        )
        gateway, _, _ = self._gateway(client=client)

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "condition mismatch",
        ):
            gateway.place_replacement(_request())

        self.assertEqual(client.place_calls, [])

    def test_safety_cap_blocks_replacement(self) -> None:
        client = _Client()
        gateway, _, _ = self._gateway(
            client=client,
            safety=_safety(
                max_order_quantity=Decimal("10"),
            ),
        )

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "max_order_qty_exceeded",
        ):
            gateway.place_replacement(_request())

        self.assertEqual(client.place_calls, [])

    def test_post_only_sell_crossing_bid_is_blocked(self) -> None:
        client = _Client()
        client.order_book = _book(
            tick_size=Decimal("0.01"),
            bids=(Decimal("0.60"),),
            asks=(Decimal("0.70"),),
        )
        gateway, _, _ = self._gateway(
            client=client,
            safety=_safety(post_only=True),
        )

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "post_only_sell_would_cross",
        ):
            gateway.place_replacement(
                _request(
                    side=OrderSide.SELL,
                    price=Decimal("0.50"),
                    tick_size=Decimal("0.01"),
                )
            )

        self.assertEqual(client.place_calls, [])

    def test_rejected_replacement_is_not_reported_as_placed(
        self,
    ) -> None:
        client = _Client()
        client.place_response = SimpleNamespace(
            ok=False,
            code="post_only_would_cross",
            message="order rejected",
        )
        gateway, _, _ = self._gateway(client=client)

        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "post_only_would_cross",
        ):
            gateway.place_replacement(_request())

    def test_client_is_cached_and_close_is_idempotent(self) -> None:
        client = _Client()
        gateway, repository, factory_calls = self._gateway(
            client=client
        )

        gateway.cancel_orders(
            account_name="primary",
            order_ids=("order-1",),
        )
        gateway.place_replacement(_request())
        gateway.close()
        gateway.close()

        self.assertEqual(repository.loads, ["primary"])
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)
        with self.assertRaisesRegex(
            PolymarketSupervisionGatewayError,
            "closed",
        ):
            gateway.place_replacement(_request())


if __name__ == "__main__":
    unittest.main()
