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
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "044_arm_xom_july_31_premarket.sql"
)
_VERIFY_ARMED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_xom_july_31_auto_live_armed.sql"
)
_VERIFY_READY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_xom_july_31_preflight_ready.sql"
)
_VERIFY_ACTIVE = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_xom_july_31_live_active.sql"
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

    def test_live_arm_is_fail_closed_and_cap_bound(self) -> None:
        text = _ARM.read_text(encoding="utf-8")

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn("live resolution heartbeat is missing or stale", text)
        self.assertIn("approved_order_quantity_cap numeric := 100", text)
        self.assertIn("approved_per_order_notional_cap numeric := 100", text)
        self.assertIn("approved_aggregate_notional_cap numeric := 1000", text)
        self.assertIn("XOM scope already contains facts or claims", text)
        self.assertNotIn("'ENABLED'", text)

    def test_live_checks_are_read_only_and_cover_each_boundary(self) -> None:
        armed = _VERIFY_ARMED.read_text(encoding="utf-8")
        ready = _VERIFY_READY.read_text(encoding="utf-8")
        active = _VERIFY_ACTIVE.read_text(encoding="utf-8")

        for text in (armed, ready, active):
            self.assertIn("BEGIN TRANSACTION READ ONLY", text)
            self.assertNotIn("INSERT INTO", text)
            self.assertNotIn("UPDATE ", text)

        self.assertIn("'PENDING'", armed)
        self.assertIn("'READY'", armed)
        self.assertIn("authenticated preflight is not ready", ready)
        self.assertIn("'ACTIVE'", active)
        self.assertIn("'ENABLED'", active)


if __name__ == "__main__":
    unittest.main()
