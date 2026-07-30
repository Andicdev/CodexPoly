from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "030_add_yum_ice_ci_july_30_premarket.sql"
)
_RUNBOOK = _ROOT / "deploy" / "lightsail" / "LIVE_MARKET_BLOCKS.md"
_CHECKLIST = _ROOT / "cbr_trading" / "SOURCE_DESIGN_CHECKLIST.md"
_CORRECTION = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "037_correct_ci_release_timing_evidence.sql"
)


class LightsailCiTimingEvidenceTests(unittest.TestCase):
    def test_ci_seed_separates_release_deadline_from_call(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        ci_row = text.split("'CI:2026-07-30'", maxsplit=1)[1]
        ci_row = ci_row.split("ON CONFLICT", maxsplit=1)[0]

        self.assertIn("2026-07-30 10:30:00+00", ci_row)
        self.assertIn("2026-07-30 12:30:00+00", ci_row)
        self.assertIn("no later than 06:30 ET", ci_row)
        self.assertIn("the 08:30 ET event is the call", ci_row)
        self.assertIn(
            "newsroom.thecignagroup.com/2026-07-07-",
            ci_row,
        )

    def test_runbook_rejects_deadline_as_earliest_signal(self) -> None:
        runbook = _RUNBOOK.read_text(encoding="utf-8")
        checklist = _CHECKLIST.read_text(encoding="utf-8")

        self.assertIn(
            "`No later than HH:MM` is only a latest-publication deadline",
            runbook,
        )
        self.assertIn(
            "`no later than HH:MM` as a latest-publication deadline",
            checklist,
        )
        self.assertIn(
            "timestamp into both fields fails review",
            runbook,
        )

    def test_catalog_correction_does_not_mutate_trading_state(self) -> None:
        text = _CORRECTION.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("UPDATE EARNINGS_RELEASE_CATALOG", upper)
        self.assertNotIn("UPDATE RESOLUTION_PROFILE_SCHEDULES", upper)
        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_PROFILES", upper)
        self.assertNotIn("INSERT INTO RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertIn("2026-07-30 10:30:00+00", text)
        self.assertIn("2026-07-30 12:30:00+00", text)


if __name__ == "__main__":
    unittest.main()
