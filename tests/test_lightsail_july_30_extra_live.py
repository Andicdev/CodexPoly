from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_ARM = (
    _ROOT / "deploy" / "lightsail" / "live"
    / "034_arm_yum_ice_ci_july_30_premarket.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_yum_ice_ci_july_30_auto_live_armed.sql"
)


class July30ExtraLiveSqlTests(unittest.TestCase):
    def test_arm_is_guarded_and_never_directly_enables(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("selected_notional <> 299.7", text)
        self.assertIn("five_profile_notional <> 499.5", text)
        self.assertIn("five_profile_notional > 1000", text)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_arm_requires_readiness_inside_ttl_window(self) -> None:
        text = _ARM.read_text(encoding="utf-8")

        self.assertIn(
            "schedule_row.state <> 'READY'",
            text,
        )
        self.assertIn("schedule_row.readiness_valid_until", text)
        self.assertIn("'2026-07-30 09:45:00+00'", text)
        self.assertIn("'2026-07-30 10:00:00+00'", text)

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("FACTS OR CLAIMS", upper)
        self.assertIn("LIVE RESOLUTION HEARTBEAT", upper)
        self.assertNotIn("SELECT *", upper)


if __name__ == "__main__":
    unittest.main()
