from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "014_switch_nvts_ir_feed_to_gcs.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_nvts_ir_feed_gcs.sql"
)


class LightsailNvtsPublicFeedFixTests(unittest.TestCase):
    def test_seed_only_switches_guarded_feed_url(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertIn("earnings:nvts:2026q2", text)
        self.assertIn(
            "navitassemi.gcs-web.com/rss/news-releases.xml",
            text,
        )
        self.assertIn("jsonb_set", text)
        self.assertIn("profile.status = 'disabled'", text)
        self.assertIn("status in ('active', 'repricing')", text)
        self.assertNotIn(
            "update resolution_execution_profiles",
            text,
        )
        self.assertNotIn(
            "update resolution_profile_schedules",
            text,
        )
        self.assertNotIn("insert into", text)
        self.assertNotIn("delete from", text)

    def test_check_is_read_only_and_preserves_historical_state(
        self,
    ) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("begin transaction read only", text)
        self.assertIn(
            "navitassemi.gcs-web.com/rss/news-releases.xml",
            text,
        )
        self.assertIn("profile.status = 'disabled'", text)
        self.assertNotIn("earnings_fact_candidates", text)
        self.assertNotIn("resolution_execution_claims", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
