from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "016_tighten_postmarket_public_source_guards.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_28_postmarket_public_source_guards.sql"
)


class PostmarketPublicSourceGuardTests(unittest.TestCase):
    def test_migration_is_guarded_and_does_not_enable_trading(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8").lower()

        self.assertIn("source_policy = jsonb_set", text)
        self.assertIn('"costar group", "q2"', text)
        self.assertIn('"to report", "conference call"', text)
        self.assertIn("status = 'disabled'", text)
        self.assertIn("status = 'shadow'", text)
        self.assertNotIn("status = 'enabled'", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)

    def test_verification_is_read_only(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("begin transaction read only", text)
        self.assertIn("csgp public-source guard mismatch", text)
        self.assertIn("nxpi public-source guard mismatch", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
