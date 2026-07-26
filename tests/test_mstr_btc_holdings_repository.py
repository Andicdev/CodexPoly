from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MstrBtcBaselineNotFound,
    MstrBtcHoldingsObservation,
    MstrBtcHoldingsStoreError,
    MstrBtcHoldingsValidationStatus,
    MstrBtcProvider,
    SqlAlchemyMstrBtcHoldingsStore,
)
from cbr_trading.mstr_btc.repository import _PIN_BASELINE_SQL


_AS_OF = datetime(2026, 7, 19, 20, 0, tzinfo=timezone.utc)
_OBSERVED = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_WINDOW_START = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)


class _MappingsResult:
    def __init__(self, row: dict[str, object] | None):
        self._row = row

    def mappings(self) -> "_MappingsResult":
        return self

    def one(self) -> dict[str, object]:
        if self._row is None:
            raise RuntimeError("expected one row")
        return self._row

    def one_or_none(self) -> dict[str, object] | None:
        return self._row


class _Session:
    def __init__(self, responses: list[dict[str, object] | None]):
        self.responses = list(responses)
        self.statements: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        params: object = None,
    ) -> _MappingsResult:
        self.statements.append((statement, params))
        if statement == "SET TRANSACTION READ ONLY":
            return _MappingsResult(None)
        return _MappingsResult(self.responses.pop(0))

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _observation(
    *,
    holdings_btc: int = 843_775,
) -> MstrBtcHoldingsObservation:
    return MstrBtcHoldingsObservation(
        holdings_btc=holdings_btc,
        as_of=_AS_OF,
        observed_at=_OBSERVED,
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-0308369",
        source_url="https://www.sec.gov/mstr-20260720.htm",
        document_fingerprint="public-document-fingerprint",
        validation_status=MstrBtcHoldingsValidationStatus.VALIDATED,
        predecessor_state_id=41,
        attributes={"source": "btc_update"},
    )


def _stored_row(
    *,
    holdings_btc: int = 843_775,
) -> dict[str, object]:
    observation = _observation(holdings_btc=holdings_btc)
    return {
        "id": 42,
        "holdings_btc": observation.holdings_btc,
        "as_of": observation.as_of,
        "observed_at": observation.observed_at,
        "provider": observation.provider.value,
        "provider_event_id": observation.provider_event_id,
        "source_url": observation.source_url,
        "document_fingerprint": observation.document_fingerprint,
        "predecessor_state_id": observation.predecessor_state_id,
        "validation_status": observation.validation_status.value,
        "attributes": {"source": "btc_update"},
    }


class MstrBtcHoldingsRepositoryTests(unittest.TestCase):
    def test_records_new_state_once(self) -> None:
        session = _Session([{"id": 42}])
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        stored = store.record_state(_observation())

        self.assertEqual(stored.row_id, 42)
        self.assertTrue(stored.created)
        self.assertTrue(session.committed)
        params = session.statements[0][1]
        assert isinstance(params, dict)
        self.assertEqual(params["holdings_btc"], 843_775)
        self.assertEqual(params["provider"], "sec")
        self.assertNotIn("UPDATE", session.statements[0][0])

    def test_identical_provider_event_is_idempotent(self) -> None:
        session = _Session([None, _stored_row()])
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        stored = store.record_state(_observation())

        self.assertEqual(stored.row_id, 42)
        self.assertFalse(stored.created)
        self.assertTrue(session.rolled_back)

    def test_conflicting_provider_event_fails_closed(self) -> None:
        session = _Session([None, _stored_row(holdings_btc=843_774)])
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(
            MstrBtcHoldingsStoreError,
            "different immutable state",
        ):
            store.record_state(_observation())

        self.assertTrue(session.rolled_back)

    def test_pins_latest_validated_state_before_boundary(self) -> None:
        session = _Session(
            [
                {
                    "id": 42,
                    "holdings_btc": 843_775,
                    "as_of": _AS_OF,
                    "provider": "sec",
                    "provider_event_id": "0001193125-26-0308369",
                    "source_url": (
                        "https://www.sec.gov/mstr-20260720.htm"
                    ),
                }
            ]
        )
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        baseline = store.pin_baseline(before=_WINDOW_START)

        self.assertEqual(baseline.state_id, "42")
        self.assertEqual(baseline.holdings_btc, 843_775)
        self.assertEqual(baseline.provider, MstrBtcProvider.SEC)
        self.assertEqual(
            session.statements[0][0],
            "SET TRANSACTION READ ONLY",
        )
        self.assertEqual(
            session.statements[1][1],
            {"before": _WINDOW_START},
        )

    def test_missing_baseline_fails_closed(self) -> None:
        session = _Session([None])
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaises(MstrBtcBaselineNotFound):
            store.pin_baseline(before=_WINDOW_START)

    def test_pin_query_rejects_late_backdated_observation(self) -> None:
        self.assertIn("as_of < :before", _PIN_BASELINE_SQL)
        self.assertIn("observed_at < :before", _PIN_BASELINE_SQL)
        self.assertNotIn("<=", _PIN_BASELINE_SQL)

    def test_naive_boundary_is_rejected_before_database_access(self) -> None:
        session = _Session([])
        store = SqlAlchemyMstrBtcHoldingsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            store.pin_baseline(before=datetime(2026, 7, 21))

        self.assertEqual(session.statements, [])


if __name__ == "__main__":
    unittest.main()
