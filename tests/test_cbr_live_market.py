from __future__ import annotations

import unittest
from types import SimpleNamespace

from cbr_trading.live.market import (
    MarketPreflightError,
    PolymarketMarketGateway,
)


CONDITION_ID = "0x" + "a" * 64


class _Paginator:
    def __init__(self, items: tuple[object, ...]):
        self._items = items

    def first_page(self) -> object:
        return SimpleNamespace(items=self._items)


class _Client:
    def __init__(self, *, active: bool = True):
        self.closed = False
        self.market = SimpleNamespace(
            condition_id=CONDITION_ID,
            question="Will the Bank of Russia decrease the key rate?",
            state=SimpleNamespace(
                active=active,
                closed=False,
                archived=False,
                accepting_orders=True,
                enable_order_book=True,
            ),
            outcomes=SimpleNamespace(
                yes=SimpleNamespace(token_id="yes-token"),
                no=SimpleNamespace(token_id="no-token"),
            ),
        )

    def list_markets(self, **kwargs: object) -> _Paginator:
        self.list_kwargs = kwargs
        return _Paginator((self.market,))

    def get_order_book(self, *, token_id: str) -> object:
        self.book_token_id = token_id
        return SimpleNamespace(
            condition_id=CONDITION_ID,
            bids=(
                SimpleNamespace(price="0.60"),
                SimpleNamespace(price="0.61"),
            ),
            asks=(
                SimpleNamespace(price="0.70"),
                SimpleNamespace(price="0.64"),
            ),
            min_order_size="5",
            tick_size="0.01",
            neg_risk=False,
            last_trade_price="0.63",
        )

    def close(self) -> None:
        self.closed = True


class MarketGatewayTests(unittest.TestCase):
    def test_loads_selected_token_and_best_prices(self) -> None:
        client = _Client()
        gateway = PolymarketMarketGateway(
            client_factory=lambda: client
        )

        snapshot = gateway.load_snapshot(
            condition_id=CONDITION_ID.upper(),
            outcome="YES",
        )

        self.assertEqual(snapshot.token_id, "yes-token")
        self.assertEqual(str(snapshot.best_bid), "0.61")
        self.assertEqual(str(snapshot.best_ask), "0.64")
        self.assertEqual(str(snapshot.last_trade_price), "0.63")
        self.assertFalse(snapshot.would_cross_buy(snapshot.best_bid))
        self.assertTrue(snapshot.would_cross_buy(snapshot.best_ask))
        self.assertTrue(client.closed)

    def test_inactive_market_is_rejected(self) -> None:
        client = _Client(active=False)
        gateway = PolymarketMarketGateway(
            client_factory=lambda: client
        )

        with self.assertRaisesRegex(
            MarketPreflightError,
            "not active",
        ):
            gateway.load_snapshot(
                condition_id=CONDITION_ID,
                outcome="NO",
            )

        self.assertTrue(client.closed)

    def test_invalid_outcome_is_rejected_before_network(self) -> None:
        with self.assertRaisesRegex(
            MarketPreflightError,
            "YES or NO",
        ):
            PolymarketMarketGateway(
                client_factory=lambda: _Client()
            ).load_snapshot(
                condition_id=CONDITION_ID,
                outcome="MAYBE",
            )


if __name__ == "__main__":
    unittest.main()
