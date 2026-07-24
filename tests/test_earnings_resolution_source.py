from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.earnings.contracts import EarningsProvider
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.sources.earnings import (
    EARNINGS_NON_GAAP_EPS_METRIC,
    EARNINGS_SOURCE_NAME,
    EarningsResolutionSource,
)
from tests.test_earnings_navitas_parser import _document, _source


_DETECTED = datetime(2026, 7, 27, 21, 0, 5, tzinfo=timezone.utc)


def _fact(value: str = "(0.03)"):
    rule = nvts_q2_2026_shadow_rule()
    result = NavitasEpsParser().parse(
        _document("June 30, 2026", value),
        source=_source(rule),
        rule=rule,
        detected_at=_DETECTED,
    )
    assert result.candidate is not None
    return result.candidate


class EarningsResolutionSourceTests(unittest.TestCase):
    def test_emits_one_canonical_signal_for_equal_official_candidates(self) -> None:
        sec = _fact()
        ir = replace(
            sec,
            provider=EarningsProvider.COMPANY_IR,
            provider_event_id="ir-release-2026q2",
            source_url="https://ir.navitassemi.com/q2-2026",
        )
        source = EarningsResolutionSource(
            candidate_provider=lambda: (ir, sec),
            rules=[nvts_q2_2026_shadow_rule()],
        )

        signals = source.poll_once()

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.signal_id, "earnings:NVTS:2026Q2")
        self.assertEqual(signal.source, EARNINGS_SOURCE_NAME)
        self.assertEqual(signal.metric, EARNINGS_NON_GAAP_EPS_METRIC)
        self.assertEqual(signal.value, Decimal("-0.03"))
        self.assertEqual(signal.attributes["period_end"], "2026-06-30")
        self.assertEqual(source.poll_once(), ())

    def test_conflicting_official_values_are_quarantined(self) -> None:
        first = _fact("(0.03)")
        second = replace(
            _fact("(0.04)"),
            provider=EarningsProvider.COMPANY_IR,
            provider_event_id="ir-release-2026q2",
            source_url="https://ir.navitassemi.com/q2-2026",
        )
        source = EarningsResolutionSource(
            candidate_provider=lambda: (first, second),
            rules=[nvts_q2_2026_shadow_rule()],
        )

        self.assertEqual(source.poll_once(), ())
        self.assertEqual(
            source.quarantine_reasons["earnings:NVTS:2026Q2"],
            "conflicting_official_candidates",
        )

    def test_unknown_scope_never_emits(self) -> None:
        candidate = replace(_fact(), scope_id="earnings:NVTS:2099Q1")
        source = EarningsResolutionSource(
            candidate_provider=lambda: (candidate,),
            rules=[nvts_q2_2026_shadow_rule()],
        )

        self.assertEqual(source.poll_once(), ())
        self.assertEqual(
            source.quarantine_reasons["earnings:NVTS:2099Q1"],
            "unknown_scope",
        )


if __name__ == "__main__":
    unittest.main()
