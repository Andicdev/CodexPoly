from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MstrBtcAuditStatus,
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcValueDerivation,
    SqlAlchemyMstrBtcAuditStore,
)


_FILED = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
_DETECTED = datetime(2026, 7, 27, 12, 0, 2, tzinfo=timezone.utc)


class _MappingsResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        if self.value is None:
            raise RuntimeError("expected one row")
        return self.value

    def one_or_none(self):
        return self.value

    def all(self):
        if self.value is None:
            return []
        if isinstance(self.value, list):
            return self.value
        return [self.value]


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.statements = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if statement == "SET TRANSACTION READ ONLY":
            return _MappingsResult(None)
        return _MappingsResult(self.responses.pop(0))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _source() -> MstrBtcDocumentCandidate:
    return MstrBtcDocumentCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-399999",
        ticker="MSTR",
        cik="1050446",
        form_type="8-K",
        source_url="https://www.sec.gov/mstr-20260727.htm",
        filing_url="https://www.sec.gov/mstr-index.htm",
        filed_at=_FILED,
        received_at=_DETECTED,
        transport_fingerprint="transport-fingerprint",
        metadata={"items": ["Item 8.01"]},
    )


def _fact() -> MstrBtcFactCandidate:
    return MstrBtcFactCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-399999",
        baseline_state_id="42",
        holdings_before_btc=843_775,
        holdings_after_btc=845_275,
        net_change_btc=1_500,
        acquired_btc=1_500,
        sold_btc=None,
        acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
        sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
        holdings_crosscheck_difference_btc=0,
        source_url="https://www.sec.gov/mstr-20260727.htm",
        filing_url="https://www.sec.gov/mstr-index.htm",
        published_at=_FILED,
        detected_at=_DETECTED,
        parser_name="mstr_btc_holdings_first",
        parser_version="1",
        document_fingerprint="document-fingerprint",
        evidence_excerpts=("Aggregate BTC Holdings 845,275",),
        attributes={"ticker": "MSTR", "cik": "1050446"},
    )


class MstrBtcAuditRepositoryTests(unittest.TestCase):
    def test_records_source_event_idempotently(self) -> None:
        first_session = _Session([{"id": 71}])
        first = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: first_session,
            text_factory=lambda value: value,
        ).record_source_event(_source())

        self.assertTrue(first.created)
        self.assertEqual(first.row_id, 71)
        self.assertTrue(first_session.committed)
        params = first_session.statements[0][1]
        self.assertEqual(params["provider"], "sec")
        self.assertNotIn("UPDATE", first_session.statements[0][0])

        duplicate_session = _Session([None, {"id": 71}])
        duplicate = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: duplicate_session,
            text_factory=lambda value: value,
        ).record_source_event(_source())

        self.assertFalse(duplicate.created)
        self.assertEqual(duplicate.row_id, 71)
        self.assertTrue(duplicate_session.rolled_back)

    def test_records_fact_and_accepted_result_without_updates(self) -> None:
        fact_session = _Session([{"id": 72}])
        store = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: fact_session,
            text_factory=lambda value: value,
        )

        stored_fact = store.record_fact(
            source_event_id=71,
            candidate=_fact(),
            reason="official_mstr_btc_update",
        )

        self.assertEqual(stored_fact.row_id, 72)
        fact_params = fact_session.statements[0][1]
        self.assertEqual(fact_params["baseline_state_id"], 42)
        self.assertEqual(fact_params["acquired_btc"], 1_500)

        result_session = _Session([{"id": 73}])
        stored_result = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: result_session,
            text_factory=lambda value: value,
        ).record_processing_result(
            source_event_id=71,
            status=MstrBtcAuditStatus.ACCEPTED,
            reason="official_mstr_btc_update",
            baseline_state_id="42",
            fact_candidate_id=72,
        )

        self.assertEqual(stored_result.row_id, 73)
        result_params = result_session.statements[0][1]
        self.assertEqual(result_params["status"], "ACCEPTED")
        self.assertEqual(result_params["fact_candidate_id"], 72)

    def test_error_result_does_not_require_fact_and_is_retryable(self) -> None:
        session = _Session([{"id": 74}])
        stored = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        ).record_processing_result(
            source_event_id=71,
            status=MstrBtcAuditStatus.ERROR,
            reason="document_fetch_failed",
            baseline_state_id=42,
        )

        self.assertEqual(stored.row_id, 74)
        self.assertIsNone(session.statements[0][1]["fact_candidate_id"])

    def test_loads_terminal_and_validated_fact_read_only(self) -> None:
        terminal_session = _Session(
            [
                {
                    "id": 73,
                    "status": "ACCEPTED",
                    "reason": "official_mstr_btc_update",
                    "baseline_state_id": 42,
                    "fact_candidate_id": 72,
                }
            ]
        )
        terminal = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: terminal_session,
            text_factory=lambda value: value,
        ).load_terminal_result(source_event_id=71)

        assert terminal is not None
        self.assertEqual(terminal.status, MstrBtcAuditStatus.ACCEPTED)
        self.assertEqual(terminal.baseline_state_id, "42")
        self.assertEqual(
            terminal_session.statements[0][0],
            "SET TRANSACTION READ ONLY",
        )

        row = {
            "scope_id": _fact().scope_id,
            "provider": "sec",
            "provider_event_id": _fact().provider_event_id,
            "baseline_state_id": 42,
            "holdings_before_btc": 843_775,
            "holdings_after_btc": 845_275,
            "net_change_btc": 1_500,
            "acquired_btc": 1_500,
            "sold_btc": None,
            "acquired_derivation": "explicit",
            "sold_derivation": "not_confirmed",
            "holdings_crosscheck_difference_btc": 0,
            "source_url": _fact().source_url,
            "filing_url": _fact().filing_url,
            "published_at": _FILED,
            "detected_at": _DETECTED,
            "parser_name": _fact().parser_name,
            "parser_version": "1",
            "document_fingerprint": "document-fingerprint",
            "evidence": ["Aggregate BTC Holdings 845,275"],
            "attributes": {"ticker": "MSTR", "cik": "1050446"},
        }
        fact_session = _Session([[row]])
        facts = SqlAlchemyMstrBtcAuditStore(
            session_factory=lambda: fact_session,
            text_factory=lambda value: value,
        ).load_validated_facts(
            scope_id="mstr-btc:2026-07-21:2026-07-27"
        )

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].acquired_btc, 1_500)
        self.assertEqual(facts[0].baseline_state_id, "42")


if __name__ == "__main__":
    unittest.main()
