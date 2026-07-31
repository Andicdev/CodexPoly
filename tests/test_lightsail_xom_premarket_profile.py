from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "037_add_xom_july_31_premarket.sql"
)
_VERIFY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_xom_july_31_premarket.sql"
)


class XomPremarketProfileTests(unittest.TestCase):
    def test_seed_is_disabled_and_uses_successor_cik(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("'earnings:XOM:2026Q2'", text)
        self.assertIn("'2115436'", text)
        self.assertIn('"predecessor_cik": "34088"', text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn("0.999", text)
        self.assertIn("quantity = 100", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertNotIn("'ENABLED'", text)

    def test_seed_has_exact_release_timing_contract(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("'2026-07-31 10:30:00+00'", text)
        self.assertIn("'2026-07-31 13:30:00+00'", text)
        self.assertIn("'OFFICIAL_EXACT'", text)
        self.assertIn("activation_safety_lead_seconds", text)
        self.assertIn("timing_contract_version", text)
        self.assertIn(
            "activate_at <= earliest_signal_at",
            text,
        )

    def test_seed_has_ir_and_businesswire_sources(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn(
            "investor.exxonmobil.com/company-information/"
            "press-releases/rss",
            text,
        )
        self.assertIn('"provider": "company_ir"', text)
        self.assertIn('"provider": "businesswire"', text)
        self.assertIn(
            "earnings_excluding_identified_items_per_common_share",
            text,
        )

    def test_verifier_is_read_only_and_checks_clean_scope(self) -> None:
        text = _VERIFY.read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("XOM scope is not clean", text)
        self.assertIn("timing_contract_version = 1", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)


if __name__ == "__main__":
    unittest.main()
