from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.execution import (
    TickSizeChangeDetector,
    TickSizeObservation,
    TickSizeObservationSource,
    TickSizeWatch,
)


OBSERVED_AT = datetime(
    2026,
    7,
    24,
    15,
    0,
    tzinfo=timezone(timedelta(hours=2)),
)


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


def _observation(
    *,
    source: TickSizeObservationSource = (
        TickSizeObservationSource.MARKET_CHANNEL_EVENT
    ),
    reported_old_tick: Decimal | None = Decimal("0.01"),
) -> TickSizeObservation:
    return TickSizeObservation(
        asset_id="asset-yes",
        tick_size=Decimal("0.001"),
        observed_at=OBSERVED_AT,
        source=source,
        reported_old_tick=reported_old_tick,
    )


class TickSizeChangeDetectorTests(unittest.TestCase):
    def test_dispatches_transition_once_across_multiple_sources(self) -> None:
        detector = _detector()
        events = []

        first = detector.dispatch(
            _observation(),
            lambda event: events.append(event) or (),
        )
        duplicate = detector.dispatch(
            _observation(
                source=TickSizeObservationSource.PERIODIC_BOOK,
                reported_old_tick=None,
            ),
            lambda event: events.append(event) or (),
        )

        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(
            first.event.event_id,
            "tick-size-change:asset-yes:0.01:0.001",
        )
        self.assertEqual(first.event.source, "market_channel_event")
        self.assertEqual(first.event.observed_at.hour, 13)
        self.assertEqual(len(events), 1)
        self.assertIsNone(duplicate)
        self.assertEqual(
            detector.current_tick("asset-yes"),
            Decimal("0.001"),
        )

    def test_handler_failure_does_not_commit_tick(self) -> None:
        detector = _detector()

        def fail(_event: object) -> tuple[()]:
            raise RuntimeError("temporary supervisor failure")

        with self.assertRaisesRegex(RuntimeError, "temporary"):
            detector.dispatch(_observation(), fail)

        self.assertEqual(
            detector.current_tick("asset-yes"),
            Decimal("0.01"),
        )
        retried = detector.dispatch(_observation(), lambda _event: ())
        self.assertIsNotNone(retried)

    def test_rejects_stale_or_unconfigured_observations(self) -> None:
        detector = _detector()
        called = []
        handler = lambda event: called.append(event) or ()

        stale = TickSizeObservation(
            asset_id="asset-yes",
            tick_size=Decimal("0.001"),
            reported_old_tick=Decimal("0.1"),
            observed_at=OBSERVED_AT,
            source=TickSizeObservationSource.MARKET_CHANNEL_EVENT,
        )
        unexpected = TickSizeObservation(
            asset_id="asset-yes",
            tick_size=Decimal("0.0001"),
            observed_at=OBSERVED_AT,
            source=TickSizeObservationSource.MARKET_CHANNEL_BOOK,
        )
        unknown = TickSizeObservation(
            asset_id="other-asset",
            tick_size=Decimal("0.001"),
            observed_at=OBSERVED_AT,
            source=TickSizeObservationSource.PERIODIC_BOOK,
        )

        self.assertIsNone(detector.dispatch(stale, handler))
        self.assertIsNone(detector.dispatch(unexpected, handler))
        self.assertIsNone(detector.dispatch(unknown, handler))
        self.assertEqual(called, [])

    def test_watch_validation_rejects_duplicates_and_coarser_tick(self) -> None:
        watch = TickSizeWatch(
            asset_id="asset-yes",
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            TickSizeChangeDetector((watch, watch))
        with self.assertRaisesRegex(ValueError, "finer"):
            TickSizeWatch(
                asset_id="asset-no",
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.1"),
            )


if __name__ == "__main__":
    unittest.main()
