from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_CATALOG = (
    _ROOT / "cbr_trading" / "migrations"
    / "019_add_earnings_release_timing.sql"
)
_SCHEDULE = (
    _ROOT / "cbr_trading" / "migrations"
    / "020_add_resolution_timing_contract.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_resolution_timing_contract_schema.sql"
)
_TRIGGER_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "staging_test_resolution_timing_contract_trigger.sql"
)


class ResolutionTimingContractMigrationTests(unittest.TestCase):
    def test_catalog_distinguishes_release_floor_from_call(self) -> None:
        text = _CATALOG.read_text(encoding="utf-8").upper()

        self.assertIn("EARLIEST_EXPECTED_RELEASE_AT", text)
        self.assertIn("CONFERENCE_CALL_AT", text)
        self.assertIn("ACTIVATION_SAFETY_LEAD_SECONDS", text)
        self.assertIn("TIMING_SOURCE_URL", text)
        self.assertNotIn("DROP TABLE", text)

    def test_auto_live_transition_is_fail_closed_without_contract(self) -> None:
        text = _SCHEDULE.read_text(encoding="utf-8").upper()

        self.assertIn("EARLIEST_SIGNAL_AT", text)
        self.assertIn("TIMING_CONTRACT_VERSION", text)
        self.assertIn("NEW.AUTOMATION_MODE <> 'AUTO_LIVE'", text)
        self.assertIn(
            "OLD.AUTOMATION_MODE IS DISTINCT FROM NEW.AUTOMATION_MODE",
            text,
        )
        self.assertIn(
            "OLD.ACTIVATE_AT IS DISTINCT FROM NEW.ACTIVATE_AT",
            text,
        )
        self.assertIn(
            "ACTIVATE_AT <= EARLIEST_SIGNAL_AT",
            text,
        )
        self.assertNotIn("DROP TABLE", text)

    def test_schema_verifier_is_read_only(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("EARNINGS_RELEASE_CATALOG_TIMING_CONTRACT_CHECK", text)
        self.assertIn(
            "RESOLUTION_PROFILE_SCHEDULES_TIMING_CONTRACT_CHECK",
            text,
        )
        self.assertIn("TRG_RESOLUTION_SCHEDULE_TIMING_CONTRACT", text)
        self.assertIn("ROLLBACK", text)
        self.assertNotIn("UPDATE ", text)

    def test_staging_trigger_probe_always_rolls_back(self) -> None:
        text = _TRIGGER_CHECK.read_text(encoding="utf-8").upper()

        self.assertIn("TIMING_CONTRACT_VERSION = 0", text)
        self.assertIn("SET AUTOMATION_MODE = 'AUTO_LIVE'", text)
        self.assertIn("SET ACTIVATE_AT =", text)
        self.assertIn("GET STACKED DIAGNOSTICS", text)
        self.assertIn("ROLLBACK", text)
        self.assertNotIn("COMMIT", text)


if __name__ == "__main__":
    unittest.main()
