from __future__ import annotations

import unittest

from cbr_trading.run_journal import (
    ResolutionRunJournalStoreError,
    SqlAlchemyResolutionRunJournalStore,
    _RECONCILE_EARNINGS_SQL,
    _RECORD_TRANSITIONS_SQL,
)


class _Mappings:
    def __init__(self, *, one=None, all_rows=()):
        self._one = one
        self._all = list(all_rows)

    def one(self):
        return self._one

    def all(self):
        return self._all


class _Result:
    def __init__(self, *, one=None, all_rows=()):
        self._mappings = _Mappings(one=one, all_rows=all_rows)

    def mappings(self):
        return self._mappings


class _Session:
    def __init__(self, *, schema_ready=True, changed_rows=()):
        self.schema_ready = schema_ready
        self.changed_rows = tuple(changed_rows)
        self.statements: list[str] = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "AS journal_table" in sql:
            return _Result(
                one={
                    "journal_table": self.schema_ready,
                    "event_table": self.schema_ready,
                    "journal_key_index": self.schema_ready,
                    "event_key_index": self.schema_ready,
                }
            )
        if sql.startswith("WITH run AS"):
            return _Result(all_rows=self.changed_rows)
        return _Result()

    def commit(self):
        self.commits += 1


class ResolutionRunJournalStoreTests(unittest.TestCase):
    def test_reconcile_verifies_schema_and_commits_both_statements(
        self,
    ) -> None:
        session = _Session(changed_rows=({"id": 10}, {"id": 11}))
        store = SqlAlchemyResolutionRunJournalStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        changed = store.reconcile_earnings()

        self.assertEqual(changed, 2)
        self.assertEqual(session.commits, 1)
        self.assertEqual(len(session.statements), 3)
        self.assertIn("AS journal_table", session.statements[0])
        self.assertEqual(
            session.statements[1],
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertEqual(
            session.statements[2],
            _RECORD_TRANSITIONS_SQL,
        )

    def test_missing_schema_fails_closed(self) -> None:
        store = SqlAlchemyResolutionRunJournalStore(
            session_factory=lambda: _Session(schema_ready=False),
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(
            ResolutionRunJournalStoreError,
            "schema is not ready",
        ):
            store.ensure_ready()

    def test_reconciliation_is_recent_incremental_and_review_safe(
        self,
    ) -> None:
        normalized = " ".join(_RECONCILE_EARNINGS_SQL.split())

        self.assertIn(
            "schedule.activate_at >= now() - interval '36 hours'",
            normalized,
        )
        self.assertIn(
            "reviewed_after_block",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertIn(
            "IS DISTINCT FROM ROW(",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertIn(
            "'source_transport', source_transport",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertIn(
            "'transport_to_fact_ms'",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertIn(
            "resolution_run_journal.details",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertNotIn(
            "coalesce(source_error",
            _RECONCILE_EARNINGS_SQL,
        )
        self.assertIn(
            "journal.updated_at >= now() - interval '10 seconds'",
            " ".join(_RECORD_TRANSITIONS_SQL.split()),
        )


if __name__ == "__main__":
    unittest.main()
