from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "007_add_rcl_earnings.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_rcl_earnings.sql"
)


class LightsailRclEarningsSeedTests(unittest.TestCase):
    def test_seed_is_idempotent_and_disarmed(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertIn("'earnings:rcl:2026q2'", text)
        self.assertIn("'earnings-rcl-2026q2'", text)
        self.assertIn(
            (
                "0x8701e9a10812190db05c6f703b4dd3d8"
                "d978ac171874c78bb26b2f23d7a38976"
            ),
            text,
        )
        self.assertIn('"kind": "html_listing"', text)
        self.assertIn('"provider": "prnewswire"', text)
        self.assertIn("on conflict (rule_key) do update", text)
        self.assertIn("on conflict (profile_key) do update", text)
        self.assertIn("'shadow'", text)
        self.assertIn("'disabled'", text)
        self.assertNotIn("'enabled'", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)
        self.assertNotIn("drop table", text)

    def test_check_is_read_only_and_requires_no_claim(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("status = 'disabled'", text)
        self.assertIn("rcl execution claim must not exist", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
