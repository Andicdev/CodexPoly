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
from cbr_trading.earnings.contracts import EarningsSourceTiming
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
        self.timings: list[EarningsSourceTiming | None] = []
        self.facts = list(existing_facts)
        self.recorded_events = 0
        self.recorded_facts = 0
        self.recorded_fact_statuses = []
        self.observed_facts = {}
        self.parse_attempts = {}
        self.parse_attempt_records = []

    def record_source_event(self, _candidate):
        self.recorded_events += 1
        return self.event

    def update_source_event_status(
        self,
        event_id: int,
        *,
        status: str,
        error: str | None = None,
        timing: EarningsSourceTiming | None = None,
    ) -> None:
        self.statuses.append((event_id, status, error))
        self.timings.append(timing)

    def claim_no_match_retry(
        self,
        *,
        source_event_id,
        parser_name,
        parser_version,
    ):
        key = (source_event_id, parser_name, parser_version)
        existing = self.parse_attempts.get(key)
        if existing not in {None, "ERROR"}:
            return False
        if any(
            fact.scope_id == nvts_q2_2026_shadow_rule().scope_id
            for fact in self.facts
        ):
            return False
        self.parse_attempts[key] = "CLAIMED"
        return True

    def record_parse_attempt(
        self,
        *,
        source_event_id,
        parser_name,
        parser_version,
        status,
        reason=None,
    ):
        key = (source_event_id, parser_name, parser_version)
        self.parse_attempts[key] = status
        self.parse_attempt_records.append(
            (key, status, reason)
        )

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate,
        reason: str,
        status: str = "VALIDATED",
    ):
        self.recorded_facts += 1
        self.recorded_fact_statuses.append(status)
        existing_observed = self.observed_facts.get(source_event_id)
        if status == "VALIDATED":
            if existing_observed is not None:
                self.facts.append(existing_observed)
                del self.observed_facts[source_event_id]
                return StoredEarningsRecord(
                    row_id=22,
                    created=False,
                    status="VALIDATED",
                )
            self.facts.append(candidate)
        elif status == "OBSERVED":
            self.observed_facts[source_event_id] = candidate
        return StoredEarningsRecord(
            row_id=22,
            created=True,
            status=status,
        )

    def promote_observed_fact(self, *, source_event_id):
        candidate = self.observed_facts.pop(source_event_id, None)
        if candidate is None:
            return None
        self.facts.append(candidate)
        return StoredEarningsRecord(
            row_id=22,
            created=False,
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


class _NavitasParserV2(NavitasEpsParser):
    parser_version = "2"


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
        self.assertEqual(
            store.recorded_fact_statuses,
            ["VALIDATED"],
        )
        self.assertEqual(
            store.parse_attempt_records[-1][1],
            "ACCEPTED",
        )
        final_timing = store.timings[-1]
        assert final_timing is not None
        self.assertEqual(
            final_timing.document_fetch_route,
            "legacy_fetch",
        )
        self.assertEqual(final_timing.fact_persisted_at, _NOW)

    def test_observation_only_fact_cannot_emit_signal(self) -> None:
        store = _Store()
        fetcher = _Fetcher(
            _document(
                "June 30, 2026",
                "(0.03)",
            ).encode()
        )
        processor = EarningsShadowProcessor(
            store=store,
            rules=[nvts_q2_2026_shadow_rule()],
            parsers={"NVTS": NavitasEpsParser()},
            document_fetcher=fetcher,
            max_fetch_attempts=1,
            fetch_retry_delay=0,
            observation_only=True,
            clock=lambda: _NOW,
            sleep=lambda _seconds: None,
        )

        result = processor.process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(
            result.status,
            ShadowProcessingStatus.OBSERVED,
        )
        self.assertIsNone(result.signal)
        self.assertEqual(
            store.recorded_fact_statuses,
            ["OBSERVED"],
        )
        self.assertEqual(store.facts, [])
        self.assertEqual(
            [status for _, status, _ in store.statuses],
            ["FETCHED", "PARSED"],
        )

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

    def test_same_parser_version_does_not_retry_terminal_no_match(
        self,
    ) -> None:
        store = _Store(
            event=StoredEarningsRecord(
                row_id=11,
                created=False,
                status="NO_MATCH",
            )
        )
        store.parse_attempts[
            (11, NavitasEpsParser.parser_name, "1")
        ] = "NO_MATCH"
        fetcher = _Fetcher(AssertionError("must not fetch"))

        result = _processor(store, fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.DUPLICATE)
        self.assertEqual(
            result.reason,
            "parser_version_already_attempted",
        )
        self.assertEqual(fetcher.calls, 0)

    def test_new_parser_version_retries_terminal_no_match_once(
        self,
    ) -> None:
        store = _Store(
            event=StoredEarningsRecord(
                row_id=11,
                created=False,
                status="NO_MATCH",
            )
        )
        store.parse_attempts[
            (11, NavitasEpsParser.parser_name, "1")
        ] = "NO_MATCH"
        fetcher = _Fetcher(
            _document("June 30, 2026", "(0.03)").encode()
        )
        parser = _NavitasParserV2()
        processor = EarningsShadowProcessor(
            store=store,
            rules=[nvts_q2_2026_shadow_rule()],
            parsers={"NVTS": parser},
            document_fetcher=fetcher,
            max_fetch_attempts=1,
            fetch_retry_delay=0,
            clock=lambda: _NOW,
            sleep=lambda _seconds: None,
        )

        result = processor.process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.SIGNAL)
        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(
            store.parse_attempts[
                (11, NavitasEpsParser.parser_name, "2")
            ],
            "ACCEPTED",
        )
        assert result.signal is not None
        self.assertEqual(str(result.signal.value), "-0.03")

    def test_no_match_retry_is_blocked_after_validated_fact(
        self,
    ) -> None:
        store = _Store(
            event=StoredEarningsRecord(
                row_id=11,
                created=False,
                status="NO_MATCH",
            ),
            existing_facts=[_accepted_fact("(0.04)")],
        )
        fetcher = _Fetcher(AssertionError("must not fetch"))
        processor = EarningsShadowProcessor(
            store=store,
            rules=[nvts_q2_2026_shadow_rule()],
            parsers={"NVTS": _NavitasParserV2()},
            document_fetcher=fetcher,
            max_fetch_attempts=1,
            fetch_retry_delay=0,
            clock=lambda: _NOW,
            sleep=lambda _seconds: None,
        )

        result = processor.process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.DUPLICATE)
        self.assertEqual(fetcher.calls, 0)

    def test_executable_transport_promotes_terminal_observation(self) -> None:
        store = _Store()
        document = _document(
            "June 30, 2026",
            "(0.03)",
        ).encode()
        observation_processor = EarningsShadowProcessor(
            store=store,
            rules=[nvts_q2_2026_shadow_rule()],
            parsers={"NVTS": NavitasEpsParser()},
            document_fetcher=_Fetcher(document),
            max_fetch_attempts=1,
            fetch_retry_delay=0,
            observation_only=True,
            clock=lambda: _NOW,
            sleep=lambda _seconds: None,
        )
        observation = observation_processor.process(
            _source(nvts_q2_2026_shadow_rule())
        )
        store.event = StoredEarningsRecord(
            row_id=11,
            created=False,
            status="PARSED",
        )
        executable_fetcher = _Fetcher(
            AssertionError("promotion must not refetch")
        )

        result = _processor(store, executable_fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(
            observation.status,
            ShadowProcessingStatus.OBSERVED,
        )
        self.assertEqual(result.status, ShadowProcessingStatus.SIGNAL)
        self.assertEqual(result.reason, "promoted_observation_signal")
        self.assertEqual(result.fact_id, 22)
        self.assertIsNotNone(result.signal)
        self.assertEqual(executable_fetcher.calls, 0)
        self.assertEqual(len(store.facts), 1)
        self.assertEqual(store.observed_facts, {})

    def test_executable_race_promotes_observation_during_parse(
        self,
    ) -> None:
        store = _Store()
        document = _document(
            "June 30, 2026",
            "(0.03)",
        ).encode()
        observation_processor = EarningsShadowProcessor(
            store=store,
            rules=[nvts_q2_2026_shadow_rule()],
            parsers={"NVTS": NavitasEpsParser()},
            document_fetcher=_Fetcher(document),
            max_fetch_attempts=1,
            fetch_retry_delay=0,
            observation_only=True,
            clock=lambda: _NOW,
            sleep=lambda _seconds: None,
        )
        observation_processor.process(
            _source(nvts_q2_2026_shadow_rule())
        )
        store.event = StoredEarningsRecord(
            row_id=11,
            created=False,
            status="FETCHED",
        )
        executable_fetcher = _Fetcher(document)

        result = _processor(store, executable_fetcher).process(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.status, ShadowProcessingStatus.SIGNAL)
        self.assertEqual(result.reason, "shadow_resolution_signal")
        self.assertEqual(executable_fetcher.calls, 1)
        self.assertEqual(
            store.recorded_fact_statuses,
            ["OBSERVED", "VALIDATED"],
        )
        self.assertEqual(len(store.facts), 1)
        self.assertEqual(store.observed_facts, {})

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
        timing = store.timings[-1]
        assert timing is not None
        self.assertIsNotNone(timing.document_fetch_started_at)
        self.assertIsNotNone(timing.document_fetch_completed_at)
        self.assertIsNone(timing.parse_started_at)

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
        self.assertEqual(
            store.parse_attempt_records[-1][1],
            "NO_MATCH",
        )
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
