from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_LIVE = (
    _ROOT / "deploy" / "lightsail" / "live"
    / "035_advance_ma_earliest_release_window.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_ma_early_window_ready_or_active.sql"
)
_RECOVER = (
    _ROOT / "deploy" / "lightsail" / "live"
    / "036_recover_ma_early_preflight.sql"
)


class MaEarlyWindowSqlTests(unittest.TestCase):
    def test_live_correction_is_guarded_and_keeps_profile_disabled(self) -> None:
        text = _LIVE.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("'PENDING'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn("'2026-07-30 10:15:00+00'", text)
        self.assertIn("'2026-07-30 10:20:00+00'", text)
        self.assertIn("'earliest_signal_at'", text)
        self.assertIn("'activation_safety_lead_minutes'", text)
        self.assertIn("RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_verifier_is_read_only_and_accepts_lifecycle_progress(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("'PREFLIGHTING', 'READY', 'ACTIVE'", text)
        self.assertIn("ROLLBACK", upper)
        self.assertNotIn("UPDATE ", upper)

    def test_recovery_reopens_only_expected_fail_closed_state(self) -> None:
        text = _RECOVER.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'BLOCKED'", text)
        self.assertIn("'preflight_not_requested'", text)
        self.assertIn("INTERVAL '3 MINUTES'", upper)
        self.assertIn("INTERVAL '5 MINUTES'", upper)
        self.assertIn("STATE = 'PENDING'", upper)
        self.assertIn("READINESS_EVIDENCE = '{}'::JSONB", upper)
        self.assertIn("RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)


if __name__ == "__main__":
    unittest.main()
