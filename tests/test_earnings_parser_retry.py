from __future__ import annotations

import unittest
from pathlib import Path

from cbr_trading.earnings.repository import SqlAlchemyEarningsStore


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "021_add_earnings_parser_attempts.sql"
)


class _Mappings:
    def __init__(self, result):
        self._result = result

    def one_or_none(self):
        return self._result

    def one(self):
        if self._result is None:
            raise AssertionError("expected one row")
        return self._result


class _Result:
    def __init__(self, result=None):
        self._result = result

    def mappings(self):
        return _Mappings(self._result)


class _Session:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.calls.append((statement, params or {}))
        return self._results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class EarningsParserRetryMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_version_unique(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS "
            "EARNINGS_SOURCE_PARSE_ATTEMPTS",
            statements,
        )
        self.assertIn(
            "SOURCE_EVENT_ID,\n        PARSER_NAME,\n        PARSER_VERSION",
            statements,
        )

    def test_claim_is_guarded_by_terminal_state_and_validated_fact(
        self,
    ) -> None:
        session = _Session([_Result({"id": 17})])
        store = SqlAlchemyEarningsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claimed = store.claim_no_match_retry(
            source_event_id=11,
            parser_name="company_eps",
            parser_version="2",
        )

        self.assertTrue(claimed)
        self.assertEqual(session.commits, 1)
        statement = session.calls[0][0]
        self.assertIn("event.status = 'NO_MATCH'", statement)
        self.assertIn(
            "fact.status IN ('VALIDATED', 'EMITTED')",
            statement,
        )
        self.assertIn(
            "ON CONFLICT (\n        source_event_id",
            statement,
        )
        self.assertNotIn(
            "UPDATE earnings_source_events",
            statement,
        )
        self.assertIn(
            "claimed_at\n                < now() - interval '5 minutes'",
            statement,
        )

    def test_same_version_claim_conflict_is_not_acquired(self) -> None:
        session = _Session([_Result(None)])
        store = SqlAlchemyEarningsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claimed = store.claim_no_match_retry(
            source_event_id=11,
            parser_name="company_eps",
            parser_version="1",
        )

        self.assertFalse(claimed)
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_parse_attempt_completion_is_versioned(self) -> None:
        session = _Session([_Result({"id": 19})])
        store = SqlAlchemyEarningsStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        store.record_parse_attempt(
            source_event_id=11,
            parser_name="company_eps",
            parser_version="2",
            status="NO_MATCH",
            reason="reviewed_shape_not_found",
        )

        self.assertEqual(session.commits, 1)
        params = session.calls[0][1]
        self.assertEqual(params["parser_version"], "2")
        self.assertEqual(params["status"], "NO_MATCH")


if __name__ == "__main__":
    unittest.main()
