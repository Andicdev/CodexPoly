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
    MstrBtcAuditStatus,
    StoredMstrBtcAuditRecord,
    mstr_jul21_27_shadow_watch,
)
from cbr_trading.mstr_btc.audit_repository import (
    StoredMstrBtcTerminalResult,
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


class _AuditStore:
    def __init__(
        self,
        *,
        terminal: StoredMstrBtcTerminalResult | None = None,
    ):
        self.terminal = terminal
        self.events = []
        self.facts = []
        self.results = []

    def record_source_event(self, candidate):
        self.events.append(candidate)
        return StoredMstrBtcAuditRecord(row_id=71, created=True)

    def load_terminal_result(self, *, source_event_id):
        self.terminal_event_id = source_event_id
        return self.terminal

    def record_fact(self, *, source_event_id, candidate, reason):
        self.facts.append((source_event_id, candidate, reason))
        return StoredMstrBtcAuditRecord(row_id=72, created=True)

    def record_processing_result(
        self,
        *,
        source_event_id,
        status,
        reason,
        baseline_state_id=None,
        fact_candidate_id=None,
    ):
        self.results.append(
            (
                source_event_id,
                status,
                reason,
                baseline_state_id,
                fact_candidate_id,
            )
        )
        return StoredMstrBtcAuditRecord(row_id=73, created=True)

    def load_validated_facts(self, *, scope_id=None):
        return tuple(
            candidate
            for _, candidate, _ in self.facts
            if scope_id is None or candidate.scope_id == scope_id
        )


class MstrBtcShadowProcessorTests(unittest.TestCase):
    def test_pins_pre_window_baseline_and_parses_without_signal(self) -> None:
        store = _Store()
        audit = _AuditStore()
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
            audit_store=audit,
            watch=mstr_jul21_27_shadow_watch(),
            document_fetcher=fetcher,
            clock=lambda: _NOW,
            sleep=lambda _: None,
        )

        result = processor.process(_candidate())

        self.assertEqual(result.status, MstrBtcShadowStatus.ACCEPTED)
        self.assertEqual(store.boundaries, [MSTR_JUL21_27_WINDOW_START])
        self.assertEqual(result.baseline_state_id, "17")
        self.assertEqual(result.source_event_id, 71)
        self.assertEqual(result.fact_candidate_id, 72)
        self.assertEqual(result.processing_result_id, 73)
        self.assertEqual(
            audit.results[0][1],
            MstrBtcAuditStatus.ACCEPTED,
        )
        self.assertEqual(len(result.signals), 3)
        assert result.fact is not None
        self.assertEqual(result.fact.acquired_btc, 1_500)
        self.assertEqual(result.fact.holdings_after_btc, 845_275)

    def test_unrelated_mstr_8k_is_no_match(self) -> None:
        result = MstrBtcShadowProcessor(
            store=_Store(),
            audit_store=_AuditStore(),
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

    def test_terminal_audit_result_prevents_refetch(self) -> None:
        fetcher = _Fetcher(b"must not be fetched")
        audit = _AuditStore(
            terminal=StoredMstrBtcTerminalResult(
                row_id=73,
                status=MstrBtcAuditStatus.ACCEPTED,
                reason="official_mstr_btc_update",
                baseline_state_id="17",
                fact_candidate_id=72,
            )
        )
        result = MstrBtcShadowProcessor(
            store=_Store(),
            audit_store=audit,
            watch=mstr_jul21_27_shadow_watch(),
            document_fetcher=fetcher,
            clock=lambda: _NOW,
            sleep=lambda _: None,
        ).process(_candidate())

        self.assertEqual(result.status, MstrBtcShadowStatus.DUPLICATE)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(result.fact_candidate_id, 72)


if __name__ == "__main__":
    unittest.main()
