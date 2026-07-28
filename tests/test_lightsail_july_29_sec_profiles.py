from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "015_add_july_29_sec_profiles.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_sec_profiles.sql"
)
_BACKLOG_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "016_catalog_remaining_july_29.sql"
)
_BACKLOG_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_catalog_backlog.sql"
)


class July29SecProfileSqlTests(unittest.TestCase):
    def test_seed_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertGreaterEqual(text.count("'DISABLED'"), 2)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'live_block', market_session", text)
        self.assertIn("'block_id'", text)
        self.assertIn("replace(lower(market_session), '_', '-')", text)
        self.assertIn("'abccbaq'", text)
        self.assertIn("0.999", text)
        self.assertIn("quantity", text)
        self.assertIn("reviewed_notional > 1000", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_fail_closed_check_is_read_only(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("AUTO_PREFLIGHT", upper)
        self.assertIn("LIVE_BLOCK", upper)
        self.assertIn("BLOCK_ID", upper)
        self.assertIn("EXECUTION CLAIM MUST NOT EXIST", upper)
        self.assertNotIn("SELECT *", upper)

    def test_remaining_catalog_is_non_executable(self) -> None:
        seed = _BACKLOG_SEED.read_text(encoding="utf-8")
        check = _BACKLOG_CHECK.read_text(encoding="utf-8")
        seed_upper = seed.upper()
        check_upper = check.upper()

        self.assertIn("'RESEARCH_PENDING'", seed)
        self.assertIn("research backlog must not create profiles", seed)
        self.assertNotIn("INSERT INTO earnings_market_rules", seed)
        self.assertNotIn("INSERT INTO resolution_execution_profiles", seed)
        self.assertNotIn("INSERT INTO resolution_profile_schedules", seed)
        self.assertNotIn("DELETE FROM", seed_upper)
        self.assertIn("BEGIN TRANSACTION READ ONLY", check_upper)
        self.assertIn("ROLLBACK", check_upper)


if __name__ == "__main__":
    unittest.main()
