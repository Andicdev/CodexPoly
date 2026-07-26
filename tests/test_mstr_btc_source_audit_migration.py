from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "009_add_mstr_btc_source_audit.sql"
)


class MstrBtcSourceAuditMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_creates_three_new_tables(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        for table in (
            "MSTR_BTC_SOURCE_EVENTS",
            "MSTR_BTC_FACT_CANDIDATES",
            "MSTR_BTC_PROCESSING_RESULTS",
        ):
            self.assertIn(
                f"CREATE TABLE IF NOT EXISTS {table}",
                statements,
            )
        self.assertNotIn("TRADING_ACCOUNTS", statements)

    def test_all_audit_tables_are_database_enforced_append_only(
        self,
    ) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8").upper()

        self.assertEqual(sql.count("BEFORE UPDATE OR DELETE"), 3)
        self.assertIn("TRG_MSTR_BTC_SOURCE_EVENTS_APPEND_ONLY", sql)
        self.assertIn("TRG_MSTR_BTC_FACT_CANDIDATES_APPEND_ONLY", sql)
        self.assertIn(
            "TRG_MSTR_BTC_PROCESSING_RESULTS_APPEND_ONLY",
            sql,
        )
        self.assertGreaterEqual(sql.count("ON DELETE RESTRICT"), 5)

    def test_error_is_retryable_but_terminal_result_is_unique(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8").upper()

        self.assertIn(
            "UX_MSTR_BTC_PROCESSING_RESULTS_TERMINAL",
            sql,
        )
        self.assertIn(
            "WHERE STATUS IN ('ACCEPTED', 'NO_MATCH', 'QUARANTINED')",
            sql,
        )
        self.assertNotIn(
            "WHERE STATUS IN "
            "('ACCEPTED', 'NO_MATCH', 'QUARANTINED', 'ERROR')",
            sql,
        )


if __name__ == "__main__":
    unittest.main()
