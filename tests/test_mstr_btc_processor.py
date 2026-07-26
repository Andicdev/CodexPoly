from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MSTR_JUL21_27_WINDOW_START,
    MstrBtcDocumentCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcProvider,
    MstrBtcShadowProcessor,
    MstrBtcShadowStatus,
    mstr_jul21_27_shadow_watch,
)


_NOW = datetime(2026, 7, 27, 12, 0, 2, tzinfo=timezone.utc)


def _candidate() -> MstrBtcDocumentCandidate:
    return MstrBtcDocumentCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-399999",
        ticker="MSTR",
        cik="1050446",
        form_type="8-K",
        source_url="https://www.sec.gov/mstr-20260727.htm",
        filing_url="https://www.sec.gov/mstr-index.htm",
        filed_at=datetime(
            2026,
            7,
            27,
            12,
            tzinfo=timezone.utc,
        ),
        received_at=_NOW,
        transport_fingerprint="transport-fingerprint",
    )


class _Store:
    def __init__(self):
        self.boundaries = []

    def pin_baseline(self, *, before):
        self.boundaries.append(before)
        return MstrBtcHoldingsBaseline(
            state_id="17",
            holdings_btc=843_775,
            as_of=datetime(
                2026,
                7,
                19,
                tzinfo=timezone.utc,
            ),
            provider=MstrBtcProvider.SEC,
            provider_event_id="baseline-accession",
            source_url="https://www.sec.gov/mstr-baseline.htm",
        )


class _Fetcher:
    def __init__(self, document: bytes):
        self.document = document
        self.calls = 0

    def fetch(self, _candidate):
        self.calls += 1
        return self.document


class MstrBtcShadowProcessorTests(unittest.TestCase):
    def test_pins_pre_window_baseline_and_parses_without_signal(self) -> None:
        store = _Store()
        fetcher = _Fetcher(
            b"""
            <h2>BTC Update</h2>
            <table>
              <tr><td>BTC Acquired</td><td>1,500</td></tr>
              <tr>
                <td>Aggregate BTC Holdings</td>
                <td>845,275</td>
              </tr>
            </table>
            <h2>ATM Update</h2>
            """
        )
        processor = MstrBtcShadowProcessor(
            store=store,
            watch=mstr_jul21_27_shadow_watch(),
            document_fetcher=fetcher,
            clock=lambda: _NOW,
            sleep=lambda _: None,
        )

        result = processor.process(_candidate())

        self.assertEqual(result.status, MstrBtcShadowStatus.ACCEPTED)
        self.assertEqual(store.boundaries, [MSTR_JUL21_27_WINDOW_START])
        self.assertEqual(result.baseline_state_id, "17")
        assert result.fact is not None
        self.assertEqual(result.fact.acquired_btc, 1_500)
        self.assertEqual(result.fact.holdings_after_btc, 845_275)

    def test_unrelated_mstr_8k_is_no_match(self) -> None:
        result = MstrBtcShadowProcessor(
            store=_Store(),
            watch=mstr_jul21_27_shadow_watch(),
            document_fetcher=_Fetcher(
                b"<h2>Item 8.01</h2><p>Unrelated filing.</p>"
            ),
            clock=lambda: _NOW,
            sleep=lambda _: None,
        ).process(_candidate())

        self.assertEqual(result.status, MstrBtcShadowStatus.NO_MATCH)
        self.assertEqual(result.reason, "btc_update_block_not_found")
        self.assertIsNone(result.fact)


if __name__ == "__main__":
    unittest.main()
