from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "008_add_mstr_btc_holdings_state.sql"
)


class MstrBtcHoldingsMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_creates_only_new_state(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS MSTR_BTC_HOLDINGS_STATE",
            statements,
        )
        self.assertNotIn("EARNINGS_MARKET_RULES", statements)
        self.assertNotIn("TRADING_ACCOUNTS", statements)

    def test_database_enforces_append_only_history(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8").upper()

        self.assertIn("BEFORE UPDATE OR DELETE", sql)
        self.assertIn(
            "TRG_MSTR_BTC_HOLDINGS_STATE_APPEND_ONLY",
            sql,
        )
        self.assertIn("ON DELETE RESTRICT", sql)

    def test_pin_index_contains_both_temporal_dimensions(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8").upper()

        self.assertIn("IX_MSTR_BTC_HOLDINGS_STATE_PIN", sql)
        self.assertIn("AS_OF DESC", sql)
        self.assertIn("OBSERVED_AT DESC", sql)
        self.assertIn("VALIDATION_STATUS = 'VALIDATED'", sql)


if __name__ == "__main__":
    unittest.main()
