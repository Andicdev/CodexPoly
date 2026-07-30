from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_ARM = (
    _ROOT / "deploy" / "lightsail" / "live"
    / "033_arm_virt_ma_july_30_premarket.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_virt_ma_july_30_auto_live_armed.sql"
)


class July30VirtMaLiveSqlTests(unittest.TestCase):
    def test_arm_is_limited_to_reviewed_profiles(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings:VIRT:2026Q2'", text)
        self.assertIn("'earnings:MA:2026Q2'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("reviewed_notional <> 199.8", text)
        self.assertIn("reviewed_notional > 1000", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_arm_requires_fresh_readiness_inside_each_ttl_window(
        self,
    ) -> None:
        text = _ARM.read_text(encoding="utf-8")

        self.assertIn("virt_state <> 'READY'", text)
        self.assertIn("ma_state <> 'READY'", text)
        self.assertIn("virt_readiness_until", text)
        self.assertIn("ma_readiness_until", text)
        self.assertIn("'2026-07-30 10:00:00+00'", text)
        self.assertIn("'2026-07-30 10:30:00+00'", text)
        self.assertIn("'2026-07-30 11:00:00+00'", text)

    def test_armed_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("FACTS OR CLAIMS", upper)
        self.assertIn("ACTIVE ORDER GROUP", upper)
        self.assertIn("LIVE RESOLUTION HEARTBEAT", upper)
        self.assertNotIn("SELECT *", upper)


if __name__ == "__main__":
    unittest.main()
