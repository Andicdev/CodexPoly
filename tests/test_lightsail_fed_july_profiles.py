from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "017_add_fed_july_shadow_profiles.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_fed_july_shadow_profiles.sql"
)


class FedJulyProfileSqlTests(unittest.TestCase):
    def test_seed_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertEqual(text.count("'fed_fomc'"), 3)
        self.assertGreaterEqual(text.count("'DISABLED'"), 3)
        self.assertIn(
            "AND status = 'ENABLED'",
            text,
        )
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'abccbaq'", text)
        self.assertIn("0.999", text)
        self.assertIn("reviewed_notional > 1000", text)
        self.assertEqual(text.count("fed:fomc:2026-07-29:"), 5)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_fail_closed_check_is_read_only(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("AUTO_PREFLIGHT", upper)
        self.assertIn("EXECUTION CLAIM MUST NOT EXIST", upper)
        self.assertIn("MUST NOT BE ENABLED", upper)
        self.assertNotIn("SELECT *", upper)
        self.assertNotIn("DELETE FROM", upper)


if __name__ == "__main__":
    unittest.main()
