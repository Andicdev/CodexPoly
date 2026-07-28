from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "014_add_resolution_run_journal.sql"
)
_BACKFILL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "006_backfill_july_28_run_journal.sql"
)


class ResolutionRunJournalSchemaTests(unittest.TestCase):
    def test_migration_is_additive_and_tracks_required_outcomes(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS RESOLUTION_RUN_JOURNAL", upper)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS RESOLUTION_RUN_JOURNAL_EVENTS",
            upper,
        )
        for value in (
            "SUCCESS",
            "LATENCY_MISS",
            "MISSED_EXECUTION",
            "WRONG_DIRECTION",
            "ERROR",
            "ACCEPTED_OPEN",
            "FILLED",
            "TOO_SLOW",
        ):
            self.assertIn(f"'{value}'", upper)
        self.assertIn("SOURCE_LATENCY_MS", upper)
        self.assertIn("DECISION_LATENCY_MS", upper)
        self.assertIn("EXCHANGE_LATENCY_MS", upper)
        self.assertIn("ERRORS JSONB", upper)
        self.assertNotIn("ALTER TABLE", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_backfill_classifies_current_runs_without_touching_orders(self) -> None:
        text = _BACKFILL.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'EARNINGS:UPS:2026Q2'", upper)
        self.assertIn("'EARNINGS:HLT:2026Q2'", upper)
        self.assertIn("'EARNINGS:RCL:2026Q2'", upper)
        self.assertIn("'LATENCY_MISS'", upper)
        self.assertIn("'MISSED_EXECUTION'", upper)
        self.assertIn("'ACCEPTED_OPEN'", upper)
        self.assertIn("MATCHED_QUANTITY", upper)
        self.assertIn("ON CONFLICT (JOURNAL_KEY) DO UPDATE", upper)
        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)


if __name__ == "__main__":
    unittest.main()
