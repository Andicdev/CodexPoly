from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_LIVE = _ROOT / "deploy" / "lightsail" / "mstr_btc" / "live"


class LightsailMstrLiveGuardTests(unittest.TestCase):
    def test_disarmed_check_is_read_only_and_scope_exact(self) -> None:
        text = (_LIVE / "000_verify_mstr_disarmed.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("expected exactly three MSTR profiles", text)
        self.assertIn(
            "scope_id = 'mstr-btc:2026-07-21:2026-07-27'",
            text,
        )
        self.assertIn("mstr_btc_source_events", text)
        self.assertIn("mstr_btc_fact_candidates", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("resolution_order_groups", text)
        self.assertIn(
            "status IN ('ACTIVE', 'REPRICING', 'FAILED')",
            text,
        )
        self.assertIn("holdings_btc = 843775", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)

    def test_activation_changes_only_three_exact_profile_statuses(
        self,
    ) -> None:
        text = (_LIVE / "001_enable_mstr_live.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("outside the guarded MSTR activation window", text)
        self.assertIn("2026-07-27 06:00:00+00", text)
        self.assertIn("2026-07-28 04:00:00+00", text)
        self.assertIn("changed_rows <> 3", text)
        self.assertIn("account_name = 'abccbaq'", text)
        self.assertIn("yes_desired_price = 0.999", text)
        self.assertIn("no_desired_price = 0.999", text)
        self.assertIn("quantity = 50", text)
        self.assertIn("status = 'ENABLED'", text)
        self.assertIn(
            "scope_id = 'mstr-btc:2026-07-21:2026-07-27'",
            text,
        )
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)

        update_clause = text.split(
            "UPDATE resolution_execution_profiles AS actual", 1
        )[1].split("FROM expected", 1)[0]
        self.assertIn("status = 'ENABLED'", update_clause)
        self.assertIn("updated_at = now()", update_clause)
        self.assertNotIn("prepare_from =", update_clause)
        self.assertNotIn("expires_at =", update_clause)
        self.assertNotIn("quantity =", update_clause)

    def test_prestart_verifier_is_read_only_and_exact(self) -> None:
        text = (
            _LIVE / "002_verify_mstr_live_prestart.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("expected exactly three enabled profiles", text)
        self.assertIn("an exact MSTR profile is not enabled", text)
        self.assertIn(
            "scope_id = 'mstr-btc:2026-07-21:2026-07-27'",
            text,
        )
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("resolution_order_groups", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)

    def test_runbook_keeps_submission_explicit_and_guarded(self) -> None:
        text = (_LIVE / "README.md").read_text(encoding="utf-8")

        self.assertIn("explicit release-time decision", text)
        self.assertIn(
            "PRODUCTION_MSTR_SUPERVISION_NO_SUBMIT",
            text,
        )
        self.assertIn("RESOLUTION_ORCHESTRATOR_MODE=preflight", text)
        self.assertIn("CBR_LIVE_TRADING_ENABLED=0", text)
        self.assertIn("RESOLUTION_ORCHESTRATOR_MODE=live", text)
        self.assertIn("RESOLUTION_SUPERVISION_ENABLED=1", text)
        self.assertIn("CBR_LIVE_TRADING_ENABLED=1", text)
        self.assertIn(
            "003_disable_all_resolution_profiles.sql",
            text,
        )
        self.assertIn("account-wide or market-wide", text)
        self.assertIn("Warm preparation must create no execution claim", text)


if __name__ == "__main__":
    unittest.main()
