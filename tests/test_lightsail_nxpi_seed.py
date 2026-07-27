from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "005_add_nxpi_earnings.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_nxpi_earnings.sql"
)


class LightsailNxpiSeedTests(unittest.TestCase):
    def test_seed_is_idempotent_and_disarmed(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertIn("nxpi-2026q2-nongaap-eps-3pt53", text)
        self.assertIn("earnings:nxpi:2026q2", text)
        self.assertIn(
            "0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4",
            text,
        )
        self.assertIn("primary_headline_non_gaap_diluted_eps", text)
        self.assertIn("investors.nxp.com/rss/news-releases.xml", text)
        self.assertIn("globenewswire", text)
        self.assertEqual(text.count("'disabled'"), 2)
        self.assertIn("on conflict (rule_key) do update", text)
        self.assertIn("on conflict (profile_key) do update", text)
        self.assertNotIn("'watching'", text)
        self.assertNotIn("'enabled'", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)

    def test_check_requires_disabled_profile_and_no_claim(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("status = 'disabled'", text)
        self.assertIn("nxpi execution claim must not exist", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
