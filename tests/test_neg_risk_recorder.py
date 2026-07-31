from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from neg_risk_trading.domain import BookLevel, OrderBook
from neg_risk_trading.market_stream import MarketStreamRun
from neg_risk_trading.polymarket import MarketStreamBootstrap
from neg_risk_trading.recorder import (
    ContinuousShadowRecorder,
    StreamObservationCollector,
)
from neg_risk_trading.repository import RecordedStreamMessage
from neg_risk_trading.settings import NegRiskRecorderSettings
from neg_risk_trading.stream import (
    LocalBookRegistry,
    StreamContractError,
    StreamStatus,
)
from tests.test_neg_risk_stream import (
    NOW_MS,
    _book_message,
    _configs,
    _event,
)


SESSION_ID = UUID("87654321-4321-8765-4321-876543218765")


def _initial_dump(event: object) -> list[dict]:
    market_by_asset = {
        asset_id: market
        for market in event.markets
        for asset_id in (
            market.yes_token_id,
            market.no_token_id,
        )
    }
    return [
        _book_message(
            asset_id=asset_id,
            condition_id=(
                market_by_asset[asset_id].condition_id
            ),
        )
        for asset_id in event.asset_ids
    ]


def _bootstrap() -> MarketStreamBootstrap:
    event = _event()
    market_by_asset = {
        asset_id: market
        for market in event.markets
        for asset_id in (
            market.yes_token_id,
            market.no_token_id,
        )
    }
    books = {}
    for asset_id in event.asset_ids:
        market = market_by_asset[asset_id]
        books[asset_id] = OrderBook(
            condition_id=market.condition_id,
            asset_id=asset_id,
            timestamp_ms=NOW_MS,
            book_hash=f"bootstrap-{asset_id}",
            bids=(
                BookLevel(
                    price=Decimal("0.40"),
                    size=Decimal("1000"),
                ),
            ),
            asks=(
                BookLevel(
                    price=Decimal("0.41"),
                    size=Decimal("1000"),
                ),
            ),
            minimum_order_size=Decimal("5"),
            tick_size=Decimal("0.01"),
            neg_risk=True,
        )
    return MarketStreamBootstrap(
        event=event,
        books=books,
        requested_at_ms=NOW_MS - 100,
        received_at_ms=NOW_MS,
        gamma_duration_ms=20,
        books_duration_ms=30,
    )


class StreamObservationCollectorTests(unittest.TestCase):
    def test_ready_initial_dump_enqueues_route_evaluation(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        registry.begin_epoch()
        payload = _initial_dump(event)
        updates = registry.apply_message(payload)
        queue: asyncio.Queue[RecordedStreamMessage | object] = (
            asyncio.Queue(maxsize=10)
        )
        collector = StreamObservationCollector(
            registry=registry,
            quantities=(Decimal("200"),),
            route_sample_interval_ms=0,
            queue=queue,
        )

        collector.on_message(payload, updates)
        record = queue.get_nowait()

        self.assertIsInstance(record, RecordedStreamMessage)
        assert isinstance(record, RecordedStreamMessage)
        self.assertEqual(record.connection_epoch, 1)
        self.assertEqual(record.message_sequence, 1)
        self.assertIsNotNone(record.route_evaluation)
        assert record.route_evaluation is not None
        self.assertEqual(
            len(record.route_evaluation["available_routes"]),
            10,
        )

    def test_full_queue_fails_closed_without_dropping(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        registry.begin_epoch()
        payload = _initial_dump(event)
        updates = registry.apply_message(payload)
        queue: asyncio.Queue[RecordedStreamMessage | object] = (
            asyncio.Queue(maxsize=1)
        )
        collector = StreamObservationCollector(
            registry=registry,
            quantities=(Decimal("200"),),
            route_sample_interval_ms=0,
            queue=queue,
        )
        collector.on_message(payload, updates)

        with self.assertRaisesRegex(
            StreamContractError,
            "^shadow_recorder_queue_full$",
        ):
            collector.on_message(payload, updates)

        self.assertEqual(queue.qsize(), 1)

    def test_irrelevant_new_market_notice_is_not_persisted(
        self,
    ) -> None:
        event = _event()
        registry = LocalBookRegistry(
            event=event,
            assets=_configs(event),
            clock_ms=lambda: NOW_MS + 10,
        )
        registry.begin_epoch()
        payload = {
            "event_type": "new_market",
            "timestamp": str(NOW_MS),
        }
        updates = registry.apply_message(payload)
        queue: asyncio.Queue[RecordedStreamMessage | object] = (
            asyncio.Queue(maxsize=10)
        )
        collector = StreamObservationCollector(
            registry=registry,
            quantities=(Decimal("200"),),
            route_sample_interval_ms=0,
            queue=queue,
        )

        collector.on_message(payload, updates)

        self.assertTrue(queue.empty())


class _FakeRepository:
    def __init__(self):
        self.ready_checks = 0
        self.starts = []
        self.batches = []
        self.reconnects = []
        self.finishes = []
        self.closed = False

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def start_session(self, start: object) -> UUID:
        self.starts.append(start)
        return SESSION_ID

    def append_batch(
        self,
        *,
        session_id: UUID,
        messages: object,
    ) -> int:
        batch = tuple(messages)
        self.batches.append((session_id, batch))
        return len(batch)

    def mark_reconnecting(self, **kwargs: object) -> None:
        self.reconnects.append(kwargs)

    def finish_session(self, **kwargs: object) -> None:
        self.finishes.append(kwargs)

    def close(self) -> None:
        self.closed = True


class _FakePublicClient:
    def __init__(self, bootstrap: MarketStreamBootstrap):
        self.bootstrap = bootstrap
        self.calls = []

    def fetch_stream_bootstrap(
        self,
        event_slug: str,
    ) -> MarketStreamBootstrap:
        self.calls.append(event_slug)
        return self.bootstrap


class _ResolvingStream:
    async def run_once(
        self,
        registry: LocalBookRegistry,
        *,
        on_message: object,
    ) -> MarketStreamRun:
        registry.begin_epoch()
        payload = _initial_dump(registry.event)
        updates = registry.apply_message(payload)
        on_message(payload, updates)
        market = registry.event.markets[0]
        resolved = {
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
        resolved_updates = registry.apply_message(resolved)
        on_message(resolved, resolved_updates)
        return MarketStreamRun(
            epoch=registry.epoch,
            message_count=2,
            update_count=len(updates) + len(resolved_updates),
            reached_ready=True,
            status_at_exit=registry.status,
        )


class ContinuousShadowRecorderTests(unittest.TestCase):
    def test_records_and_finishes_halted_without_live_actions(
        self,
    ) -> None:
        bootstrap = _bootstrap()
        repository = _FakeRepository()
        public_client = _FakePublicClient(bootstrap)
        settings = NegRiskRecorderSettings(
            database_url="sqlite://",
            database_target="test",
            event_slug=bootstrap.event.slug,
            quantities=(Decimal("200"),),
            queue_capacity=100,
            write_batch_size=10,
            flush_interval_seconds=0.01,
            route_sample_interval_ms=0,
        )
        recorder = ContinuousShadowRecorder(
            settings=settings,
            repository=repository,
            public_client=public_client,
            stream=_ResolvingStream(),
        )

        asyncio.run(recorder.run())

        self.assertEqual(repository.ready_checks, 1)
        self.assertEqual(
            public_client.calls,
            [bootstrap.event.slug],
        )
        self.assertEqual(len(repository.starts), 1)
        metadata = repository.starts[0].metadata
        self.assertEqual(
            metadata["route_directions"],
            ["MAKER_BUY", "MAKER_SELL"],
        )
        self.assertEqual(
            metadata["event_contract"]["version"],
            1,
        )
        persisted = [
            message
            for _session_id, batch in repository.batches
            for message in batch
        ]
        self.assertEqual(len(persisted), 2)
        self.assertIsNotNone(persisted[0].route_evaluation)
        self.assertIsNone(persisted[1].route_evaluation)
        self.assertEqual(repository.reconnects, [])
        self.assertEqual(len(repository.finishes), 1)
        self.assertEqual(
            repository.finishes[0]["status"],
            "HALTED",
        )
        self.assertTrue(repository.closed)


class RecorderSettingsTests(unittest.TestCase):
    def test_only_shadow_mode_is_accepted(self) -> None:
        settings = NegRiskRecorderSettings(
            database_url="sqlite://",
        )
        settings.validate()

        with self.assertRaisesRegex(
            ValueError,
            "must remain 'shadow'",
        ):
            NegRiskRecorderSettings(
                mode="live",
                database_url="sqlite://",
            ).validate()


if __name__ == "__main__":
    unittest.main()
