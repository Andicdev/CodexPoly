from __future__ import annotations

import unittest
from pathlib import Path


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "cbr_trading"
    / "migrations"
    / "007_add_trading_account_metadata.sql"
)


class TradingAccountMetadataMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_contains_no_credentials(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8")
        normalized = text.casefold()

        self.assertIn(
            "create table if not exists trading_account_metadata",
            normalized,
        )
        self.assertIn("wallet_address", normalized)
        self.assertIn("signature_type", normalized)
        self.assertNotIn("private_key", normalized)
        self.assertNotIn("master_key", normalized)
        self.assertNotIn("api_key", normalized)
        self.assertNotIn("drop table", normalized)
        self.assertNotIn("alter table", normalized)
        self.assertNotIn("delete from", normalized)


if __name__ == "__main__":
    unittest.main()
