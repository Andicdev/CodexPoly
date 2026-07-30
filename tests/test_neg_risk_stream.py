from __future__ import annotations

import asyncio
import json
import unittest
from decimal import Decimal

from neg_risk_trading.domain import (
    FeeSchedule,
    NegRiskEvent,
    OutcomeMarket,
    RewardConfig,
)
from neg_risk_trading.market_stream import (
    MARKET_STREAM_URL,
    MarketStreamTransportError,
    PolymarketMarketStream,
)
from neg_risk_trading.stream import (
    LocalBookRegistry,
    QueueAheadBounds,
    StreamAssetConfig,
    StreamContractError,
    StreamStatus,
)


NOW_MS = 2_000_000_000_000


def _condition(index: int) -> str:
    marker = format(index + 10, "x")
    return "0x" + marker * 64


def _event() -> NegRiskEvent:
    markets = []
    for index in range(5):
        markets.append(
            OutcomeMarket(
                market_id=f"market-{index}",
                condition_id=_condition(index),
                slug=f"fed-outcome-{index}",
                question=f"Fed outcome {index}?",
                yes_token_id=str(10_000 + index),
                no_token_id=str(20_000 + index),
                fee_schedule=FeeSchedule(
                    rate=Decimal("0.05"),
                    exponent=1,
                    taker_only=True,
                    rebate_rate=Decimal("0.25"),
                ),
                rewards=RewardConfig(
                    minimum_size=Decimal("200"),
                    maximum_spread_cents=Decimal("4.5"),
                    daily_rate=Decimal("1000"),
                ),
            )
        )
    return NegRiskEvent(
        event_id="fed-september",
        slug="fed-decision-in-september-762",
        title="Fed Decision in September?",
        neg_risk=True,
        augmented=False,
        markets=tuple(markets),
    )


def _configs(event: NegRiskEvent) -> tuple[StreamAssetConfig, ...]:
    market_by_asset = {
        asset_id: market
        for market in event.markets
        for asset_id in (
            market.yes_token_id,
            market.no_token_id,
        )
    }
    return tuple(
        StreamAssetConfig(
            asset_id=asset_id,
            condition_id=market_by_asset[asset_id].condition_id,
            minimum_order_size=Decimal("5"),
            tick_size=Decimal("0.01"),
        )
        for asset_id in event.asset_ids
    )


def _book_message(
    *,
    asset_id: str,
    condition_id: str,
    timestamp_ms: int = NOW_MS,
) -> dict:
    return {
        "event_type": "book",
        "market": condition_id,
        "asset_id": asset_id,
        "timestamp": str(timestamp_ms),
        "hash": f"hash-{asset_id}-{timestamp_ms}",
        "bids": [
            {"price": "0.40", "size": "1000"},
            {"price": "0.39", "size": "500"},
        ],
        "asks": [
            {"price": "0.41", "size": "900"},
            {"price": "0.42", "size": "600"},
        ],
    }


class LocalBookRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = _event()
        self.received_at_ms = NOW_MS + 10
        self.registry = LocalBookRegistry(
            event=self.event,
            assets=_configs(self.event),
            clock_ms=lambda: self.received_at_ms,
        )

    def _bootstrap(self) -> None:
        self.registry.begin_epoch()
        messages = []
        market_by_asset = {
            asset_id: market
            for market in self.event.markets
            for asset_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        }
        for asset_id in self.event.asset_ids:
            messages.append(
                _book_message(
                    asset_id=asset_id,
                    condition_id=(
                        market_by_asset[asset_id].condition_id
                    ),
                )
            )
        updates = self.registry.apply_message(messages)
        self.assertEqual(len(updates), 10)

    def test_all_yes_and_no_books_are_required_for_ready(
        self,
    ) -> None:
        epoch = self.registry.begin_epoch()
        market = self.event.markets[0]

        update = self.registry.apply_message(
            _book_message(
                asset_id=market.yes_token_id,
                condition_id=market.condition_id,
            )
        )[0]

        self.assertEqual(epoch, 1)
        self.assertEqual(
            self.registry.status,
            StreamStatus.BOOTSTRAPPING,
        )
        self.assertFalse(update.became_ready)
        self._bootstrap_remaining()
        self.assertTrue(self.registry.ready)
        self.assertEqual(len(self.registry.views()), 10)

    def test_price_change_updates_depth_and_infers_finer_tick(
        self,
    ) -> None:
        self._bootstrap()
        market = self.event.markets[0]

        update = self.registry.apply_message(
            {
                "event_type": "price_change",
                "market": market.condition_id,
                "timestamp": str(NOW_MS + 1),
                "price_changes": [
                    {
                        "asset_id": market.yes_token_id,
                        "price": "0.40",
                        "size": "0",
                        "side": "BUY",
                        "hash": "changed-hash",
                        "best_bid": "0.395",
                        "best_ask": "0.41",
                    },
                    {
                        "asset_id": market.yes_token_id,
                        "price": "0.395",
                        "size": "250",
                        "side": "BUY",
                        "hash": "changed-hash",
                        "best_bid": "0.395",
                        "best_ask": "0.41",
                    },
                ],
            }
        )[0]
        book = self.registry.view(market.yes_token_id)

        self.assertEqual(
            update.affected_asset_ids,
            (market.yes_token_id,),
        )
        self.assertEqual(book.best_bid.price, Decimal("0.395"))
        self.assertEqual(book.best_bid.size, Decimal("250"))
        self.assertEqual(book.tick_size, Decimal("0.001"))
        self.assertEqual(book.book_hash, "changed-hash")
        self.assertTrue(self.registry.ready)

    def test_top_of_book_mismatch_marks_epoch_suspect(
        self,
    ) -> None:
        self._bootstrap()
        market = self.event.markets[0]

        with self.assertRaisesRegex(
            StreamContractError,
            "^price_change_best_bid_mismatch$",
        ):
            self.registry.apply_message(
                {
                    "event_type": "price_change",
                    "market": market.condition_id,
                    "timestamp": str(NOW_MS + 1),
                    "price_changes": [
                        {
                            "asset_id": market.yes_token_id,
                            "price": "0.40",
                            "size": "800",
                            "side": "BUY",
                            "hash": "changed-hash",
                            "best_bid": "0.38",
                            "best_ask": "0.41",
                        }
                    ],
                }
            )

        self.assertEqual(
            self.registry.status,
            StreamStatus.SUSPECT,
        )
        self.assertEqual(
            self.registry.reason_code,
            "price_change_best_bid_mismatch",
        )

    def test_reconnect_invalidates_books_until_every_snapshot_arrives(
        self,
    ) -> None:
        self._bootstrap()
        self.registry.disconnect()
        epoch = self.registry.begin_epoch()
        market = self.event.markets[0]

        self.registry.apply_message(
            _book_message(
                asset_id=market.yes_token_id,
                condition_id=market.condition_id,
                timestamp_ms=NOW_MS + 2,
            )
        )

        self.assertEqual(epoch, 2)
        self.assertEqual(
            self.registry.status,
            StreamStatus.RESYNCING,
        )
        self.assertFalse(self.registry.ready)

    def test_tick_change_updates_order_tick(self) -> None:
        self._bootstrap()
        market = self.event.markets[0]

        self.registry.apply_message(
            {
                "event_type": "tick_size_change",
                "market": market.condition_id,
                "asset_id": market.yes_token_id,
                "old_tick_size": "0.01",
                "new_tick_size": "0.001",
                "timestamp": str(NOW_MS + 1),
            }
        )

        self.assertEqual(
            self.registry.view(
                market.yes_token_id
            ).tick_size,
            Decimal("0.001"),
        )

    def test_timestamp_regression_marks_epoch_suspect(self) -> None:
        self._bootstrap()
        market = self.event.markets[0]

        with self.assertRaisesRegex(
            StreamContractError,
            "^stream_timestamp_regressed$",
        ):
            self.registry.apply_message(
                _book_message(
                    asset_id=market.yes_token_id,
                    condition_id=market.condition_id,
                    timestamp_ms=NOW_MS - 1,
                )
            )

        self.assertEqual(
            self.registry.status,
            StreamStatus.SUSPECT,
        )

    def test_market_resolution_halts_registry(self) -> None:
        self._bootstrap()
        market = self.event.markets[0]

        update = self.registry.apply_message(
            {
                "event_type": "market_resolved",
                "market": market.condition_id,
                "assets_ids": [
                    market.yes_token_id,
                    market.no_token_id,
                ],
                "winning_asset_id": market.yes_token_id,
                "winning_outcome": "Yes",
                "timestamp": str(NOW_MS + 1),
            }
        )[0]

        self.assertEqual(update.status, StreamStatus.HALTED)
        self.assertEqual(
            set(update.affected_asset_ids),
            {market.yes_token_id, market.no_token_id},
        )

    def _bootstrap_remaining(self) -> None:
        market_by_asset = {
            asset_id: market
            for market in self.event.markets
            for asset_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        }
        initialized = set(self.registry.views())
        for asset_id in self.event.asset_ids:
            if asset_id in initialized:
                continue
            self.registry.apply_message(
                _book_message(
                    asset_id=asset_id,
                    condition_id=(
                        market_by_asset[asset_id].condition_id
                    ),
                )
            )


class QueueAheadBoundsTests(unittest.TestCase):
    def test_queue_is_preserved_and_narrowed_without_forced_cancel(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        registry.begin_epoch()
        market = event.markets[0]
        registry.apply_message(
            _book_message(
                asset_id=market.yes_token_id,
                condition_id=market.condition_id,
            )
        )
        queue = QueueAheadBounds.before_placement(
            registry.view(market.yes_token_id),
            side="SELL",
            price=Decimal("0.41"),
            own_size=Decimal("200"),
        )

        queue.observe_aggregate_size(
            Decimal("1000"),
            includes_own_order=True,
        )

        self.assertEqual(queue.ahead_lower, Decimal("800"))
        self.assertEqual(queue.ahead_upper, Decimal("800"))
        self.assertEqual(queue.own_remaining, Decimal("200"))

        queue.observe_own_fill(Decimal("25"))

        self.assertEqual(queue.ahead_lower, Decimal("0"))
        self.assertEqual(queue.ahead_upper, Decimal("0"))
        self.assertEqual(queue.own_remaining, Decimal("175"))


class _FakeSocket:
    def __init__(self, messages: list[object]):
        self.messages = list(messages)
        self.sent: list[str] = []

    async def __aenter__(self) -> _FakeSocket:
        return self

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None

    async def send(self, value: str) -> None:
        self.sent.append(value)

    async def recv(self) -> object:
        if self.messages:
            return self.messages.pop(0)
        await asyncio.Future()


class _FakeConnector:
    def __init__(self, socket: _FakeSocket):
        self.socket = socket
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs: object) -> _FakeSocket:
        self.calls.append((url, dict(kwargs)))
        return self.socket


class MarketStreamTransportTests(unittest.TestCase):
    def test_subscribes_all_assets_and_processes_initial_dump(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        market_by_asset = {
            asset_id: market
            for market in event.markets
            for asset_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        }
        initial_dump = [
            _book_message(
                asset_id=asset_id,
                condition_id=(
                    market_by_asset[asset_id].condition_id
                ),
            )
            for asset_id in event.asset_ids
        ]
        socket = _FakeSocket([json.dumps(initial_dump)])
        connector = _FakeConnector(socket)
        observed = []
        stream = PolymarketMarketStream(
            connector=connector,
            heartbeat_seconds=60,
        )

        result = asyncio.run(
            stream.run_once(
                registry,
                on_update=observed.append,
                maximum_messages=1,
            )
        )

        self.assertEqual(connector.calls[0][0], MARKET_STREAM_URL)
        subscription = json.loads(socket.sent[0])
        self.assertEqual(
            subscription["assets_ids"],
            list(event.asset_ids),
        )
        self.assertTrue(subscription["initial_dump"])
        self.assertTrue(
            subscription["custom_feature_enabled"]
        )
        self.assertTrue(result.reached_ready)
        self.assertEqual(
            result.status_at_exit,
            StreamStatus.READY,
        )
        self.assertEqual(result.update_count, 10)
        self.assertEqual(len(observed), 10)
        self.assertEqual(
            registry.status,
            StreamStatus.DISCONNECTED,
        )

    def test_malformed_message_marks_registry_suspect(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        socket = _FakeSocket(["{not-json"])
        stream = PolymarketMarketStream(
            connector=_FakeConnector(socket),
            heartbeat_seconds=60,
        )

        with self.assertRaisesRegex(
            StreamContractError,
            "^market_stream_json_invalid$",
        ):
            asyncio.run(
                stream.run_once(
                    registry,
                    maximum_messages=1,
                )
            )

        self.assertEqual(
            registry.status,
            StreamStatus.SUSPECT,
        )

    def test_ready_stream_fails_closed_without_heartbeat(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        market_by_asset = {
            asset_id: market
            for market in event.markets
            for asset_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        }
        initial_dump = [
            _book_message(
                asset_id=asset_id,
                condition_id=(
                    market_by_asset[asset_id].condition_id
                ),
            )
            for asset_id in event.asset_ids
        ]
        socket = _FakeSocket([json.dumps(initial_dump)])
        stream = PolymarketMarketStream(
            connector=_FakeConnector(socket),
            heartbeat_seconds=0.01,
        )

        with self.assertRaisesRegex(
            MarketStreamTransportError,
            "^market_stream_heartbeat_timeout$",
        ):
            asyncio.run(
                stream.run_once(
                    registry,
                    maximum_messages=2,
                )
            )

        self.assertEqual(
            registry.status,
            StreamStatus.DISCONNECTED,
        )


if __name__ == "__main__":
    unittest.main()
