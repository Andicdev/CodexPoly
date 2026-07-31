from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "038_add_july_31_premarket_batch.sql"
)
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "045_arm_july_31_premarket_batch.sql"
)
_ARMED_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_31_premarket_batch_auto_live_armed.sql"
)
_PREFLIGHT_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_31_premarket_seven_preflight_ready.sql"
)
_LIVE_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_31_premarket_seven_live_active.sql"
)


class July31PremarketBatchTests(unittest.TestCase):
    def test_seed_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        for scope in (
            "earnings:BEN:2026Q3",
            "earnings:CBOE:2026Q2",
            "earnings:CVX:2026Q2",
            "earnings:CL:2026Q2",
            "earnings:MRNA:2026Q2",
            "earnings:ARES:2026Q2",
        ):
            self.assertIn(scope, text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertNotIn("'ENABLED'", text)

    def test_seed_uses_default_order_template_and_timing_guard(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("0.999, 0.999, 100", text)
        self.assertIn("'reprice_on_tick_change', 0.01, 0.001, 1", text)
        self.assertIn("'2026-07-31 08:30:00+00'", text)
        self.assertIn("'2026-07-31 08:45:00+00'", text)
        self.assertIn("activate_at <= earliest_signal_at", text)
        self.assertIn("'OFFICIAL_EXACT'", text)
        self.assertIn("'HISTORICAL_PATTERN'", text)

    def test_seed_catalog_separates_release_and_call_times(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("conference_call_at", text)
        self.assertIn("earliest_expected_release_at", text)
        self.assertIn(
            "Release timing is kept separate from conference-call time",
            text,
        )

    def test_arm_is_fail_closed_and_cap_bound(self) -> None:
        text = _ARM.read_text(encoding="utf-8")

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("live resolution heartbeat is missing or stale", text)
        self.assertIn("batch_notional <> 599.4", text)
        self.assertIn("block_notional <> 699.3", text)
        self.assertIn("block_notional > 1000", text)
        self.assertIn("authenticated readiness is not fresh", text)

    def test_runtime_checks_are_read_only_and_cover_all_seven(self) -> None:
        armed_text = _ARMED_CHECK.read_text(encoding="utf-8")
        preflight_text = _PREFLIGHT_CHECK.read_text(encoding="utf-8")
        live_text = _LIVE_CHECK.read_text(encoding="utf-8")

        for text in (armed_text, preflight_text, live_text):
            self.assertIn("BEGIN TRANSACTION READ ONLY", text)
            self.assertIn("live resolution heartbeat is missing or stale", text)
            self.assertIn("earnings:ARES:2026Q2", text)
            self.assertIn("ROLLBACK", text)
        self.assertIn("earnings:XOM:2026Q2", preflight_text)
        self.assertIn("earnings:XOM:2026Q2", live_text)
        self.assertIn("state = 'READY'", preflight_text)
        self.assertIn("profile.status = 'DISABLED'", preflight_text)
        self.assertIn("state = 'ACTIVE'", live_text)
        self.assertIn("profile.status = 'ENABLED'", live_text)


if __name__ == "__main__":
    unittest.main()
