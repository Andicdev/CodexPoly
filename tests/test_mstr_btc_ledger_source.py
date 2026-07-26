from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MSTR_JUL21_27_WINDOW_START,
    MstrBtcAuditStatus,
    MstrBtcHoldingsBaseline,
    MstrBtcLedgerDocumentFetcher,
    MstrBtcLedgerParser,
    MstrBtcProvider,
    MstrBtcShadowProcessor,
    MstrBtcShadowStatus,
    StoredMstrBtcAuditRecord,
    StrategyLedgerClient,
    evaluate_mstr_btc_ledger,
    mstr_jul21_27_ledger_watch,
    parse_strategy_ledger_html,
)
from cbr_trading.earnings.hosted_worker import EarningsHostedShadowWorker
from cbr_trading.earnings.settings import EarningsWorkerSettings


_DETECTED_AT = datetime(
    2026,
    7,
    27,
    12,
    0,
    2,
    tzinfo=timezone.utc,
)
_FILING_URL = (
    "https://assets.contentstack.io/v3/assets/"
    "example/form-8-k_07-27-2026.pdf"
)


def _raw_row(
    *,
    uid: str,
    row_index: int,
    reported_date: str,
    count: int,
    holdings: int,
) -> dict[str, object]:
    return {
        "uid": uid,
        "row_index": row_index,
        "date_of_purchase": reported_date,
        "count": count,
        "btc_holdings": holdings,
        "sec": {"url": _FILING_URL},
    }


def _ledger_html(rows: list[dict[str, object]]) -> bytes:
    next_data = {
        "buildId": "ledger-build",
        "props": {
            "pageProps": {
                "bitcoinData": rows,
            }
        },
    }
    return (
        "<html><body><script id=\"__NEXT_DATA__\" "
        "type=\"application/json\">"
        + json.dumps(next_data)
        + "</script></body></html>"
    ).encode("utf-8")


def _baseline_row() -> dict[str, object]:
    return _raw_row(
        uid="baseline-row",
        row_index=116,
        reported_date="2026-07-06",
        count=-2_225,
        holdings=843_775,
    )


def _snapshot(*rows: dict[str, object]):
    return parse_strategy_ledger_html(
        _ledger_html([_baseline_row(), *rows]),
        fetched_at=_DETECTED_AT,
    )


class _Response:
    def __init__(
        self,
        *,
        status_code: int,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, *, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class _BaselineStore:
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


class _AuditStore:
    def __init__(self):
        self.events = []
        self.facts = []
        self.results = []

    def record_source_event(self, candidate):
        self.events.append(candidate)
        return StoredMstrBtcAuditRecord(row_id=71, created=True)

    def load_terminal_result(self, *, source_event_id):
        return None

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


class _LedgerClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0
        self.closed = False

    def fetch_snapshot(self):
        self.calls += 1
        if self.calls == 1:
            return self.snapshot
        return None

    def close(self):
        self.closed = True


class StrategyLedgerSourceTests(unittest.TestCase):
    def test_current_baseline_page_does_not_emit_candidate(self) -> None:
        decision = evaluate_mstr_btc_ledger(
            _snapshot(),
            watch=mstr_jul21_27_ledger_watch(),
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "no_new_ledger_rows")

    def test_signed_rows_are_aggregated_and_crosschecked(self) -> None:
        snapshot = _snapshot(
            _raw_row(
                uid="purchase-row",
                row_index=117,
                reported_date="2026-07-24",
                count=1_500,
                holdings=845_275,
            ),
            _raw_row(
                uid="sale-row",
                row_index=118,
                reported_date="2026-07-26",
                count=-32,
                holdings=845_243,
            ),
        )

        decision = evaluate_mstr_btc_ledger(
            snapshot,
            watch=mstr_jul21_27_ledger_watch(),
        )

        self.assertTrue(decision.accepted)
        assert decision.candidate is not None
        self.assertEqual(
            decision.candidate.provider,
            MstrBtcProvider.STRATEGY_LEDGER,
        )
        self.assertEqual(
            decision.candidate.provider_event_id,
            "ledger:117-118:sale-row",
        )
        rows = decision.candidate.metadata["ledger_rows"]
        self.assertEqual([row["btc_change"] for row in rows], [1500, -32])

        document = MstrBtcLedgerDocumentFetcher().fetch(
            decision.candidate
        )
        parsed = MstrBtcLedgerParser().parse(
            document,
            source=decision.candidate,
            baseline=_BaselineStore().pin_baseline(
                before=MSTR_JUL21_27_WINDOW_START
            ),
            detected_at=_DETECTED_AT,
        )

        self.assertEqual(parsed.status.value, "accepted")
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.acquired_btc, 1_500)
        self.assertEqual(parsed.candidate.sold_btc, 32)
        self.assertEqual(parsed.candidate.net_change_btc, 1_468)
        self.assertEqual(parsed.candidate.holdings_after_btc, 845_243)

    def test_missing_row_or_running_holdings_mismatch_is_rejected(
        self,
    ) -> None:
        missing = evaluate_mstr_btc_ledger(
            _snapshot(
                _raw_row(
                    uid="gap",
                    row_index=118,
                    reported_date="2026-07-26",
                    count=10,
                    holdings=843_785,
                )
            ),
            watch=mstr_jul21_27_ledger_watch(),
        )
        mismatch = evaluate_mstr_btc_ledger(
            _snapshot(
                _raw_row(
                    uid="bad-holdings",
                    row_index=117,
                    reported_date="2026-07-26",
                    count=10,
                    holdings=843_900,
                )
            ),
            watch=mstr_jul21_27_ledger_watch(),
        )

        self.assertEqual(missing.reason, "ledger_row_sequence_invalid")
        self.assertEqual(
            mismatch.reason,
            "ledger_running_holdings_mismatch",
        )

    def test_shared_processor_persists_fact_and_builds_signals(self) -> None:
        decision = evaluate_mstr_btc_ledger(
            _snapshot(
                _raw_row(
                    uid="purchase-row",
                    row_index=117,
                    reported_date="2026-07-26",
                    count=1_500,
                    holdings=845_275,
                )
            ),
            watch=mstr_jul21_27_ledger_watch(),
        )
        assert decision.candidate is not None
        store = _BaselineStore()
        audit = _AuditStore()
        processor = MstrBtcShadowProcessor(
            store=store,
            audit_store=audit,
            watch=mstr_jul21_27_ledger_watch(),
            document_fetcher=MstrBtcLedgerDocumentFetcher(),
            parser=MstrBtcLedgerParser(),
            clock=lambda: _DETECTED_AT,
            sleep=lambda _: None,
        )

        result = processor.process(decision.candidate)

        self.assertEqual(result.status, MstrBtcShadowStatus.ACCEPTED)
        self.assertEqual(store.boundaries, [MSTR_JUL21_27_WINDOW_START])
        self.assertEqual(len(result.signals), 3)
        self.assertEqual(
            audit.results[0][1],
            MstrBtcAuditStatus.ACCEPTED,
        )

    def test_http_client_uses_conditional_requests_and_deduplicates(
        self,
    ) -> None:
        document = _ledger_html([_baseline_row()])
        session = _Session(
            (
                _Response(
                    status_code=200,
                    content=document,
                    headers={"ETag": '"ledger-etag"'},
                ),
                _Response(
                    status_code=200,
                    content=document,
                    headers={"ETag": '"ledger-etag"'},
                ),
            )
        )
        client = StrategyLedgerClient(session=session)

        first = client.fetch_snapshot(fetched_at=_DETECTED_AT)
        second = client.fetch_snapshot(fetched_at=_DETECTED_AT)
        client.close()

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("Mozilla/5.0", session.calls[0][1]["User-Agent"])
        self.assertEqual(
            session.calls[1][1]["If-None-Match"],
            '"ledger-etag"',
        )
        self.assertTrue(session.closed)


class StrategyLedgerHostedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_polls_ledger_independently_of_sec_cycle(
        self,
    ) -> None:
        snapshot = _snapshot(
            _raw_row(
                uid="purchase-row",
                row_index=117,
                reported_date="2026-07-26",
                count=1_500,
                holdings=845_275,
            )
        )
        ledger_client = _LedgerClient(snapshot)
        audit = _AuditStore()
        worker = EarningsHostedShadowWorker(
            settings=EarningsWorkerSettings(
                database_url="postgresql://configured",
                sec_api_key="configured",
                http_user_agent="CodexPoly test@example.com",
                mstr_btc_shadow_enabled=True,
                mstr_btc_ledger_enabled=True,
            ),
            store=object(),
            mstr_store=_BaselineStore(),
            mstr_audit_store=audit,
            ledger_client=ledger_client,
        )

        result = await worker.run_ledger_poll_cycle()
        duplicate_snapshot = await worker.run_ledger_poll_cycle()

        assert result is not None
        self.assertEqual(result.status, MstrBtcShadowStatus.ACCEPTED)
        self.assertEqual(len(result.signals), 3)
        self.assertIsNone(duplicate_snapshot)
        self.assertEqual(len(audit.facts), 1)


if __name__ == "__main__":
    unittest.main()
