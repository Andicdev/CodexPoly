from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.processor import (
    EarningsShadowProcessor,
    ShadowProcessingStatus,
)
from cbr_trading.earnings.repository import StoredEarningsRecord
from tests.test_earnings_navitas_parser import _document, _source


_NOW = datetime(2026, 7, 27, 21, 0, 5, tzinfo=timezone.utc)


class _Store:
    def __init__(
        self,
        *,
        event: StoredEarningsRecord | None = None,
        existing_facts=(),
    ):
        self.event = event or StoredEarningsRecord(
            row_id=11,
            created=True,
            status="RECEIVED",
        )
        self.statuses: list[tuple[int, str, str | None]] = []
        self.facts = list(existing_facts)
        self.recorded_events = 0
        self.recorded_facts = 0

    def record_source_event(self, _candidate):
        self.recorded_events += 1
        return self.event

    def update_source_event_status(
        self,
        event_id: int,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        self.statuses.append((event_id, status, error))

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate,
        reason: str,
    ):
        self.recorded_facts += 1
        self.facts.append(candidate)
        return StoredEarningsRecord(
            row_id=22,
            created=True,
            status="VALIDATED",
        )

    def load_validated_facts(self, *, scope_id=None):
        return tuple(
            fact
            for fact in self.facts
            if scope_id is None or fact.scope_id == scope_id
        )


class _Fetcher:
    def __init__(self, document: bytes | Exception):
        self.document = document
        self.calls = 0

    def fetch(self, _candidate):
        self.calls += 1
        if isinstance(self.document, Exception):
            raise self.document
        return self.document


def _processor(store: _Store, fetcher: _Fetcher):
    return EarningsShadowProcessor(
        store=store,
        rules=[nvts_q2_2026_shadow_rule()],
        parsers={"NVTS": NavitasEpsParser()},
        document_fetcher=fetcher,
        max_fetch_attempts=3,
        fetch_retry_delay=0,
        clock=lambda: _NOW,
        sleep=lambda _seconds: None,
    )


def _accepted_fact(value: str):
    rule = nvts_q2_2026_shadow_rule()
    result = NavitasEpsParser().parse(
        _document("June 30, 2026", value),
        source=_source(rule),
        rule=rule,
        detected_at=_NOW,
    )
    assert result.candidate is not None
    return result.candidate


class EarningsShadowProcessorTests(unittest.TestCase):
    def test_persists_fact_and_builds_shadow_signal(self) -> None:
        store = _Store()
        fetcher = _Fetcher(
            _document(
                "June 30, 2026",
                "(0.03)",
            ).encode()
        )

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.SIGNAL)
        self.assertEqual(result.event_id, 11)
        self.assertEqual(result.fact_id, 22)
        assert result.signal is not None
        self.assertEqual(str(result.signal.value), "-0.03")
        self.assertEqual(
            [status for _, status, _ in store.statuses],
            ["FETCHED", "PARSED"],
        )
        self.assertEqual(store.recorded_facts, 1)

    def test_terminal_duplicate_does_not_fetch_or_parse(self) -> None:
        store = _Store(
            event=StoredEarningsRecord(
                row_id=11,
                created=False,
                status="PARSED",
            )
        )
        fetcher = _Fetcher(AssertionError("must not fetch"))

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.DUPLICATE)
        self.assertEqual(fetcher.calls, 0)
        self.assertEqual(store.recorded_facts, 0)

    def test_fetch_failure_retries_then_records_type_only_error(self) -> None:
        secret = "credential-that-must-not-leak"
        store = _Store()
        fetcher = _Fetcher(RuntimeError(secret))

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.ERROR)
        self.assertEqual(fetcher.calls, 3)
        error = store.statuses[-1][2]
        self.assertIsNotNone(error)
        assert error is not None
        self.assertNotIn(secret, error)
        self.assertIn("RuntimeError", error)

    def test_missing_metric_is_no_match_not_no_resolution(self) -> None:
        store = _Store()
        fetcher = _Fetcher(
            (
                "<p>Three Months Ended June 30, 2026</p>"
                "<p>GAAP diluted loss per share $ (0.20)</p>"
            ).encode()
        )

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.NO_MATCH)
        self.assertEqual(store.statuses[-1][1], "NO_MATCH")
        self.assertIsNone(result.signal)

    def test_conflicting_official_fact_is_quarantined(self) -> None:
        store = _Store(existing_facts=[_accepted_fact("(0.04)")])
        fetcher = _Fetcher(
            _document(
                "June 30, 2026",
                "(0.03)",
            ).encode()
        )

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(
            result.status,
            ShadowProcessingStatus.QUARANTINED,
        )
        self.assertEqual(
            result.reason,
            "conflicting_official_candidates",
        )
        self.assertEqual(store.statuses[-1][1], "QUARANTINED")


if __name__ == "__main__":
    unittest.main()
