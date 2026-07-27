from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "004_seed_earnings_release_catalog_2026-07-28.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_earnings_release_catalog_2026-07-28.sql"
)


class EarningsReleaseCatalogSeedTests(unittest.TestCase):
    def test_seed_is_catalog_only_and_idempotent(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertIn("insert into earnings_release_catalog", text)
        self.assertIn("on conflict (event_key) do update", text)
        self.assertEqual(text.count("'parser_only'"), 5)
        self.assertIn("'sbux:2026-07-29'", text)
        self.assertNotIn("earnings_market_rules", text)
        self.assertNotIn("resolution_execution_profiles", text)
        self.assertNotIn("delete from", text)
        self.assertNotIn("drop table", text)

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("earnings release catalog seed is incomplete", text)
        self.assertIn("parser-only catalog classification mismatch", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
