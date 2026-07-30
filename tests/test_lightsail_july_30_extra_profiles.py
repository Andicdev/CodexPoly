from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT / "deploy" / "lightsail" / "seeds"
    / "030_add_yum_ice_ci_july_30_premarket.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_yum_ice_ci_july_30_premarket.sql"
)


class July30ExtraProfilesSqlTests(unittest.TestCase):
    def test_seed_is_three_profile_non_live_batch(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        for ticker in ("YUM", "ICE", "CI"):
            self.assertIn(f"'earnings:{ticker}:2026Q2'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("reviewed_notional <> 299.7", text)
        self.assertIn("reviewed_notional > 1000", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_declares_three_source_routes(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertEqual(text.count('"provider":"sec_api"'), 3)
        self.assertEqual(text.count('"provider":"sec"'), 3)
        self.assertGreaterEqual(
            text.count('"provider": "businesswire"'),
            3,
        )

    def test_verifier_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("FACTS OR CLAIMS", upper)
        self.assertNotIn("SELECT *", upper)


if __name__ == "__main__":
    unittest.main()
