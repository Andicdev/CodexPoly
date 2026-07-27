from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "012_add_ba_prnewswire_source.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_ba_prnewswire_source.sql"
)


class LightsailBoeingPressWireSeedTests(unittest.TestCase):
    def test_seed_only_adds_guarded_source_policy(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertIn("earnings:ba:2026q2", text)
        self.assertIn('"provider": "prnewswire"', text)
        self.assertIn("www.prnewswire.com", text)
        self.assertIn("jsonb_set", text)
        self.assertIn("2026-07-28 09:45:00+00", text)
        self.assertIn("2026-07-28 10:00:00+00", text)
        self.assertIn("profile.status = 'disabled'", text)
        self.assertIn("schedule.state = 'pending'", text)
        self.assertNotIn("update resolution_execution_profiles", text)
        self.assertNotIn("update resolution_profile_schedules", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("delete from", text)

    def test_check_is_read_only_and_requires_no_execution_state(
        self,
    ) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("begin transaction read only", text)
        self.assertIn("2026-07-28 09:45:00+00", text)
        self.assertIn("2026-07-28 10:00:00+00", text)
        self.assertIn("a ba execution claim already exists", text)
        self.assertIn("an active ba order group already exists", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
