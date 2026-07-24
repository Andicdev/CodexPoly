from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.execution import (
    TickSizeChangeDetector,
    TickSizeObservationSource,
    TickSizeWatch,
)
from cbr_trading.live.market_channel import (
    MarketChannelError,
    PolymarketMarketChannel,
    PolymarketTickObservationAdapter,
)


OBSERVED_AT = datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc)


def _detector() -> TickSizeChangeDetector:
    return TickSizeChangeDetector(
        (
            TickSizeWatch(
                asset_id="asset-yes",
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.001"),
            ),
        )
    )


def _level(price: str) -> object:
    return SimpleNamespace(price=price, size="10")


def _book(
    *,
    tick_size: str | None,
    bids: tuple[object, ...] = (),
    asks: tuple[object, ...] = (),
) -> object:
    return SimpleNamespace(
        token_id="asset-yes",
        tick_size=tick_size,
        bids=bids,
        asks=asks,
        timestamp=OBSERVED_AT,
    )


def _event(event_type: str, payload: object) -> object:
    return SimpleNamespace(type=event_type, payload=payload)


def _tick_event(
    *,
    old_tick: str = "0.01",
    new_tick: str = "0.001",
) -> object:
    return _event(
        "tick_size_change",
        SimpleNamespace(
            token_id="asset-yes",
            old_tick_size=old_tick,
            new_tick_size=new_tick,
            timestamp=OBSERVED_AT,
        ),
    )


class _Supervisor:
    def __init__(self, *, fail_once: bool = False):
        self.events = []
        self._fail_once = fail_once

    def on_tick_size_change(self, event: object) -> tuple[()]:
        self.events.append(event)
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("temporary failure")
        return ()


class _Handle:
    def __init__(self, events: tuple[object, ...]):
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> "_Handle":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(
        self,
        events: tuple[object, ...] = (),
        *,
        subscribe_error: Exception | None = None,
    ):
        self.handle = _Handle(events)
        self.subscribe_error = subscribe_error
        self.spec = None
        self.closed = False

    async def subscribe(self, spec: object) -> _Handle:
        self.spec = spec
        if self.subscribe_error is not None:
            raise self.subscribe_error
        return self.handle

    async def close(self) -> None:
        self.closed = True


class TickObservationAdapterTests(unittest.TestCase):
    def test_maps_explicit_tick_event(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )

        observation = adapter.observation_for_event(_tick_event())

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.asset_id, "asset-yes")
        self.assertEqual(observation.tick_size, Decimal("0.001"))
        self.assertEqual(
            observation.reported_old_tick,
            Decimal("0.01"),
        )
        self.assertEqual(
            observation.source,
            TickSizeObservationSource.MARKET_CHANNEL_EVENT,
        )

    def test_uses_explicit_tick_from_book(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )

        observation = adapter.observation_for_book(
            _book(tick_size="0.001"),
            source=TickSizeObservationSource.PERIODIC_BOOK,
        )

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.tick_size, Decimal("0.001"))
        self.assertEqual(
            observation.source,
            TickSizeObservationSource.PERIODIC_BOOK,
        )

    def test_book_level_can_prove_expected_finer_tick(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )

        observation = adapter.observation_for_event(
            _event(
                "book",
                _book(
                    tick_size=None,
                    bids=(_level("0.99"),),
                    asks=(_level("0.999"),),
                ),
            )
        )

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.tick_size, Decimal("0.001"))
        self.assertEqual(
            observation.source,
            TickSizeObservationSource.MARKET_CHANNEL_BOOK_LEVEL,
        )

    def test_aligned_book_levels_do_not_prove_a_change(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )

        observation = adapter.observation_for_event(
            _event(
                "book",
                _book(
                    tick_size=None,
                    bids=(_level("0.98"), _level("0.99")),
                    asks=(_level("0.97"),),
                ),
            )
        )

        self.assertIsNone(observation)

    def test_live_price_change_level_can_prove_finer_tick(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )
        payload = SimpleNamespace(
            timestamp=OBSERVED_AT,
            price_changes=(
                SimpleNamespace(
                    token_id="asset-yes",
                    price="0.999",
                    size="12",
                ),
            ),
        )

        observations = adapter.observations_for_event(
            _event("price_change", payload)
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(
            observations[0].source,
            TickSizeObservationSource.MARKET_CHANNEL_PRICE_LEVEL,
        )

    def test_removed_price_level_is_not_tick_evidence(self) -> None:
        adapter = PolymarketTickObservationAdapter(
            detector=_detector()
        )
        payload = SimpleNamespace(
            timestamp=OBSERVED_AT,
            price_changes=(
                SimpleNamespace(
                    token_id="asset-yes",
                    price="0.999",
                    size="0",
                ),
            ),
        )

        observations = adapter.observations_for_event(
            _event("price_change", payload)
        )

        self.assertEqual(observations, ())


class MarketChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribes_exact_assets_and_routes_tick_once(self) -> None:
        detector = _detector()
        supervisor = _Supervisor()
        client = _Client(
            (
                _event("price_change", SimpleNamespace()),
                _tick_event(),
                _event(
                    "book",
                    _book(tick_size="0.001"),
                ),
            )
        )
        channel = PolymarketMarketChannel(
            detector=detector,
            supervisor=supervisor,
            client_factory=lambda: client,
        )

        dispatches = await channel.run()

        self.assertEqual(len(dispatches), 1)
        self.assertEqual(len(supervisor.events), 1)
        self.assertEqual(tuple(client.spec.token_ids), ("asset-yes",))
        self.assertFalse(client.spec.custom_feature_enabled)
        self.assertTrue(client.handle.closed)
        self.assertTrue(client.closed)

    async def test_supervisor_failure_is_retryable_on_later_evidence(
        self,
    ) -> None:
        supervisor = _Supervisor(fail_once=True)
        client = _Client((_tick_event(), _tick_event()))
        channel = PolymarketMarketChannel(
            detector=_detector(),
            supervisor=supervisor,
            client_factory=lambda: client,
            logger=logging.getLogger("test.market-channel"),
        )

        dispatches = await channel.run()

        self.assertEqual(len(supervisor.events), 2)
        self.assertEqual(len(dispatches), 1)

    async def test_subscription_error_is_sanitized(self) -> None:
        client = _Client(
            subscribe_error=RuntimeError(
                "DATABASE_URL=postgres://user:password@example/db"
            )
        )
        channel = PolymarketMarketChannel(
            detector=_detector(),
            supervisor=_Supervisor(),
            client_factory=lambda: client,
        )

        with self.assertRaises(MarketChannelError) as raised:
            await channel.run()

        self.assertNotIn("password", str(raised.exception))
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
