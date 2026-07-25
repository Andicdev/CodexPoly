from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_LIVE = _ROOT / "deploy" / "lightsail" / "live"


class LightsailNvtsLiveGuardTests(unittest.TestCase):
    def test_disarmed_check_is_read_only_and_replay_safe(self) -> None:
        text = (_LIVE / "000_verify_nvts_disarmed.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("status = 'VALIDATED'", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("resolution_order_groups", text)
        self.assertIn("status IN ('ACTIVE', 'REPRICING')", text)
        self.assertIn("status = 'DISABLED'", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)

    def test_activation_changes_only_the_exact_profile_status(self) -> None:
        text = (_LIVE / "001_enable_nvts_live.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("outside the guarded NVTS activation window", text)
        self.assertIn("2026-07-27 19:00:00+00", text)
        self.assertIn("2026-07-28 03:00:00+00", text)
        self.assertIn("profile_key = 'earnings-nvts-2026q2'", text)
        self.assertIn("account_name = 'abccbaq'", text)
        self.assertIn("yes_desired_price = 0.999", text)
        self.assertIn("no_desired_price = 0.999", text)
        self.assertIn("quantity = 50", text)
        self.assertIn("status = 'VALIDATED'", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("resolution_order_groups", text)
        self.assertIn("status = 'ENABLED'", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)

        update_clause = text.split(
            "UPDATE resolution_execution_profiles", 1
        )[1].split("WHERE profile_key", 1)[0]
        self.assertIn("status = 'ENABLED'", update_clause)
        self.assertIn("updated_at = now()", update_clause)
        self.assertNotIn("prepare_from =", update_clause)
        self.assertNotIn("expires_at =", update_clause)
        self.assertNotIn("quantity =", update_clause)

    def test_prestart_verifier_is_read_only_and_exact(self) -> None:
        text = (
            _LIVE / "002_verify_nvts_live_prestart.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("expected exactly one enabled profile", text)
        self.assertIn("profile_key = 'earnings-nvts-2026q2'", text)
        self.assertIn("status = 'VALIDATED'", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("resolution_order_groups", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)

    def test_disarm_is_additive_and_fail_closed(self) -> None:
        text = (
            _LIVE / "003_disable_all_resolution_profiles.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("UPDATE resolution_execution_profiles", text)
        self.assertIn("status = 'DISABLED'", text)
        self.assertIn("WHERE status <> 'DISABLED'", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)
        self.assertNotIn("TRUNCATE", text)

    def test_runbook_keeps_live_transition_explicit(self) -> None:
        text = (_LIVE / "README.md").read_text(encoding="utf-8")

        self.assertIn("explicit release-time approval", text)
        self.assertIn("RESOLUTION_ORCHESTRATOR_MODE=preflight", text)
        self.assertIn("CBR_LIVE_TRADING_ENABLED=0", text)
        self.assertIn("RESOLUTION_ORCHESTRATOR_MODE=live", text)
        self.assertIn("RESOLUTION_SUPERVISION_ENABLED=1", text)
        self.assertIn("CBR_LIVE_TRADING_ENABLED=1", text)
        self.assertIn("003_disable_all_resolution_profiles.sql", text)
        self.assertIn("account-wide or market-wide", text)


if __name__ == "__main__":
    unittest.main()
