from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "019_reconcile_july_29_carryovers.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_carryovers.sql"
)


class July29CarryoverSqlTests(unittest.TestCase):
    def test_seed_reconciles_etsy_without_making_it_executable(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("'ETSY:2026-08-05'", text)
        self.assertIn("DATE '2026-08-05'", text)
        self.assertIn("'POST_MARKET'", text)
        self.assertIn("'RESEARCH_PENDING'", text)
        self.assertIn("must not create a profile", text)
        self.assertNotIn("'earnings-etsy-2026q2'", text)

    def test_wwd_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings-wwd-2026q3'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("'2026-07-29-post-market'", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("EXECUTION CLAIM MUST NOT EXIST", upper)
        self.assertIn("WWD AUTO_PREFLIGHT SCHEDULE MISMATCH", upper)
        self.assertNotIn("SELECT *", upper)


if __name__ == "__main__":
    unittest.main()
