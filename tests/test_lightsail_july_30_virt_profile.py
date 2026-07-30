from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_TDAY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "027_reconcile_tday_official_schedule.sql"
)
_VIRT = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "028_add_virt_july_30_premarket.sql"
)
_VERIFY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_virt_july_30_premarket.sql"
)


class July30VirtProfileTests(unittest.TestCase):
    def test_tday_is_catalog_only_on_official_august_date(self) -> None:
        text = _TDAY.read_text(encoding="utf-8")
        self.assertIn("'TDAY:2026-08-06'", text)
        self.assertIn("'CANCELLED'", text)
        self.assertIn("'RESEARCH_PENDING'", text)
        self.assertIn("TDAY executable state must not exist", text)
        self.assertNotIn(
            "INSERT INTO resolution_execution_profiles",
            text,
        )

    def test_virt_seed_is_disabled_and_preliminary_safe(self) -> None:
        text = _VIRT.read_text(encoding="utf-8")
        self.assertIn("'earnings:VIRT:2026Q2'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn('"reject_preliminary_results": true', text)
        self.assertIn("'2026-07-30 11:00:00+00'", text)
        self.assertIn("0.999", text)
        self.assertIn("quantity = 100", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertNotIn("'ENABLED'", text)

    def test_virt_verifier_is_read_only(self) -> None:
        text = _VERIFY.read_text(encoding="utf-8")
        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("VIRT scope is not clean", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)


if __name__ == "__main__":
    unittest.main()
