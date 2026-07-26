from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MSTR_PURCHASE_ANY_SIGNAL_ID,
    MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
    MSTR_SALE_ANY_SIGNAL_ID,
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcValueDerivation,
    mstr_jul21_27_resolution_rules,
)
from cbr_trading.sources.mstr_btc import (
    MSTR_BTC_ACQUIRED_METRIC,
    MSTR_BTC_SOLD_METRIC,
    MstrBtcResolutionSource,
)


_PUBLISHED = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
_DETECTED = datetime(2026, 7, 27, 12, 0, 2, tzinfo=timezone.utc)


def _fact(
    *,
    acquired: int | None,
    sold: int | None,
    net_change: int,
    acquired_derivation: MstrBtcValueDerivation,
    sold_derivation: MstrBtcValueDerivation,
) -> MstrBtcFactCandidate:
    before = 843_775
    return MstrBtcFactCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-399999",
        baseline_state_id="42",
        holdings_before_btc=before,
        holdings_after_btc=before + net_change,
        net_change_btc=net_change,
        acquired_btc=acquired,
        sold_btc=sold,
        acquired_derivation=acquired_derivation,
        sold_derivation=sold_derivation,
        holdings_crosscheck_difference_btc=0,
        source_url="https://www.sec.gov/mstr-20260727.htm",
        filing_url="https://www.sec.gov/mstr-index.htm",
        published_at=_PUBLISHED,
        detected_at=_DETECTED,
        parser_name="mstr_btc_holdings_first",
        parser_version="1",
        document_fingerprint="document-fingerprint",
        evidence_excerpts=("Aggregate BTC Holdings",),
        attributes={"ticker": "MSTR", "cik": "1050446"},
    )


class MstrBtcResolutionSourceTests(unittest.TestCase):
    def test_purchase_fact_fans_out_to_three_market_scopes(self) -> None:
        source = MstrBtcResolutionSource(
            candidate_provider=lambda: (
                _fact(
                    acquired=1_500,
                    sold=None,
                    net_change=1_500,
                    acquired_derivation=(
                        MstrBtcValueDerivation.EXPLICIT
                    ),
                    sold_derivation=(
                        MstrBtcValueDerivation.NOT_CONFIRMED
                    ),
                ),
            ),
            rules=mstr_jul21_27_resolution_rules(),
        )

        signals = source.poll_once()
        by_id = {signal.signal_id: signal for signal in signals}

        self.assertEqual(
            set(by_id),
            {
                MSTR_PURCHASE_ANY_SIGNAL_ID,
                MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
                MSTR_SALE_ANY_SIGNAL_ID,
            },
        )
        self.assertEqual(
            by_id[MSTR_PURCHASE_ANY_SIGNAL_ID].metric,
            MSTR_BTC_ACQUIRED_METRIC,
        )
        self.assertEqual(
            int(by_id[MSTR_PURCHASE_ANY_SIGNAL_ID].value),
            1_500,
        )
        self.assertEqual(
            int(by_id[MSTR_PURCHASE_OVER_1000_SIGNAL_ID].value),
            1_500,
        )
        self.assertEqual(
            by_id[MSTR_SALE_ANY_SIGNAL_ID].metric,
            MSTR_BTC_SOLD_METRIC,
        )
        self.assertEqual(
            int(by_id[MSTR_SALE_ANY_SIGNAL_ID].value),
            0,
        )
        self.assertEqual(
            by_id[MSTR_SALE_ANY_SIGNAL_ID].attributes["derivation"],
            "crosscheck_zero",
        )
        self.assertEqual(source.poll_once(), ())

    def test_sale_fact_resolves_purchase_as_zero_by_crosscheck(self) -> None:
        source = MstrBtcResolutionSource(
            candidate_provider=lambda: (
                _fact(
                    acquired=None,
                    sold=32,
                    net_change=-32,
                    acquired_derivation=(
                        MstrBtcValueDerivation.NOT_CONFIRMED
                    ),
                    sold_derivation=MstrBtcValueDerivation.EXPLICIT,
                ),
            ),
            rules=mstr_jul21_27_resolution_rules(),
        )

        by_id = {
            signal.signal_id: signal
            for signal in source.poll_once()
        }

        self.assertEqual(
            int(by_id[MSTR_PURCHASE_ANY_SIGNAL_ID].value),
            0,
        )
        self.assertEqual(
            int(by_id[MSTR_PURCHASE_OVER_1000_SIGNAL_ID].value),
            0,
        )
        self.assertEqual(
            int(by_id[MSTR_SALE_ANY_SIGNAL_ID].value),
            32,
        )

    def test_inferred_quantity_at_1000_boundary_is_quarantined(self) -> None:
        source = MstrBtcResolutionSource(
            candidate_provider=lambda: (
                _fact(
                    acquired=1_000,
                    sold=None,
                    net_change=1_000,
                    acquired_derivation=(
                        MstrBtcValueDerivation.HOLDINGS_DELTA
                    ),
                    sold_derivation=(
                        MstrBtcValueDerivation.NOT_CONFIRMED
                    ),
                ),
            ),
            rules=mstr_jul21_27_resolution_rules(),
        )

        signals = source.poll_once()

        self.assertEqual(
            {signal.signal_id for signal in signals},
            {
                MSTR_PURCHASE_ANY_SIGNAL_ID,
                MSTR_SALE_ANY_SIGNAL_ID,
            },
        )
        self.assertEqual(
            source.quarantine_reasons[
                MSTR_PURCHASE_OVER_1000_SIGNAL_ID
            ],
            "explicit_acquisition_required_near_boundary",
        )

    def test_conflicting_official_facts_quarantine_all_scopes(self) -> None:
        first = _fact(
            acquired=1_500,
            sold=None,
            net_change=1_500,
            acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
            sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
        )
        second = replace(
            first,
            provider=MstrBtcProvider.STRATEGY_LEDGER,
            provider_event_id="strategy-ledger-row",
            holdings_after_btc=845_274,
            net_change_btc=1_499,
            acquired_btc=1_499,
        )
        source = MstrBtcResolutionSource(
            candidate_provider=lambda: (first, second),
            rules=mstr_jul21_27_resolution_rules(),
        )

        self.assertEqual(source.poll_once(), ())
        self.assertEqual(
            set(source.quarantine_reasons.values()),
            {"conflicting_official_candidates"},
        )


if __name__ == "__main__":
    unittest.main()
