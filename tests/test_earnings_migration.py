from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "004_add_earnings_source_tables.sql"
)


class EarningsMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_creates_only_new_tables(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS EARNINGS_MARKET_RULES",
            statements,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS EARNINGS_SOURCE_EVENTS",
            statements,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS EARNINGS_FACT_CANDIDATES",
            statements,
        )

    def test_earnings_source_layer_has_no_execution_dependency(self) -> None:
        paths = (
            _ROOT / "cbr_trading" / "earnings",
            _ROOT / "cbr_trading" / "sources" / "earnings.py",
        )
        contents: list[str] = []
        for path in paths:
            if path.is_dir():
                contents.extend(
                    file.read_text(encoding="utf-8")
                    for file in path.rglob("*.py")
                )
            else:
                contents.append(path.read_text(encoding="utf-8"))
        source = "\n".join(contents)

        self.assertNotIn("cbr_trading.execution", source)
        self.assertNotIn("PreparedExecutor", source)
        self.assertNotIn("OrderIntent", source)


if __name__ == "__main__":
    unittest.main()
