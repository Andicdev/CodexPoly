from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.fed import (
    FedOfficialObservation,
    FedRateBucket,
    FedRateDecision,
    fed_july_2026_decision_spec,
)
from cbr_trading.sources import (
    FED_RATE_CHANGE_METRIC,
    FED_SOURCE_NAME,
    FedResolutionSource,
    fed_rate_bucket,
    normalize_fed_delta_bps,
    resolution_signal_from_fed_observation,
)


_NOW = datetime(2026, 7, 29, 18, tzinfo=timezone.utc)


def _observation(
    *,
    lower: str,
    upper: str,
) -> FedOfficialObservation:
    return FedOfficialObservation(
        provider="fed_board_statement_html",
        source_url=(
            "https://www.federalreserve.gov/newsevents/"
            "pressreleases/monetary20260729a.htm"
        ),
        decision=FedRateDecision(
            lower=Decimal(lower),
            upper=Decimal(upper),
        ),
        detected_at=_NOW,
        document_fingerprint="a" * 64,
        excerpt="target range for the federal funds rate",
    )


class FedResolutionSourceTests(unittest.TestCase):
    def test_builds_no_change_signal_against_upper_bound(self) -> None:
        spec = fed_july_2026_decision_spec()
        signal = resolution_signal_from_fed_observation(
            _observation(lower="3.50", upper="3.75"),
            spec=spec,
        )

        self.assertEqual(signal.source, FED_SOURCE_NAME)
        self.assertEqual(signal.metric, FED_RATE_CHANGE_METRIC)
        self.assertEqual(signal.value, Decimal("0"))
        self.assertEqual(signal.direction, "no_change")
        self.assertEqual(signal.attributes["bucket"], "no_change")
        self.assertEqual(
            signal.attributes["current_upper_percent"],
            "3.75",
        )

    def test_rounds_nonstandard_change_away_from_zero(self) -> None:
        self.assertEqual(
            normalize_fed_delta_bps(Decimal("12.5")),
            Decimal("25"),
        )
        self.assertEqual(
            normalize_fed_delta_bps(Decimal("-12.5")),
            Decimal("-25"),
        )
        self.assertEqual(
            normalize_fed_delta_bps(Decimal("37.5")),
            Decimal("50"),
        )

    def test_maps_all_normalized_buckets(self) -> None:
        expected = {
            Decimal("-75"): FedRateBucket.DECREASE_50_PLUS,
            Decimal("-25"): FedRateBucket.DECREASE_25,
            Decimal("0"): FedRateBucket.NO_CHANGE,
            Decimal("25"): FedRateBucket.INCREASE_25,
            Decimal("75"): FedRateBucket.INCREASE_50_PLUS,
        }
        self.assertEqual(
            {
                value: fed_rate_bucket(value)
                for value in expected
            },
            expected,
        )

    def test_profile_scoped_adapter_reuses_event_signal(self) -> None:
        event_signal = resolution_signal_from_fed_observation(
            _observation(lower="3.75", upper="4"),
            spec=fed_july_2026_decision_spec(),
        )
        source = FedResolutionSource(
            lambda: event_signal,
            scope_id="fed:test:increase-25",
        )

        scoped = source.poll_once()[0]

        self.assertEqual(scoped.signal_id, "fed:test:increase-25")
        self.assertEqual(scoped.value, Decimal("25"))
        self.assertEqual(event_signal.value, scoped.value)


if __name__ == "__main__":
    unittest.main()
