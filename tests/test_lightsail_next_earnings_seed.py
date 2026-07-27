from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "006_add_ba_czr_csgp_earnings.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_ba_czr_csgp_earnings.sql"
)


class LightsailNextEarningsSeedTests(unittest.TestCase):
    def test_seed_has_three_idempotent_disarmed_profiles(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        for ticker in ("ba", "czr", "csgp"):
            self.assertIn(f"earnings:{ticker.upper()}:2026q2".lower(), text)
            self.assertIn(f"'earnings-{ticker}-2026q2'", text)
        for condition_id in (
            "0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f",
            "0x13805b2ba317a2c26ff596bb59534c23c4808fd26eac9be6f847977b92fd6bf3",
            "0xb71e441b6853dc1c3e1480b6d772b63cd8a907e706c1b1a4862c3ffa794ac418",
        ):
            self.assertIn(condition_id, text)

        self.assertEqual(text.count("'disabled'"), 4)
        self.assertIn("on conflict (rule_key) do update", text)
        self.assertIn("on conflict (profile_key) do update", text)
        self.assertNotIn("'enabled'", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)

    def test_check_is_read_only_and_requires_no_claims(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("status = 'disabled'", text)
        self.assertIn(
            "next earnings execution claim must not exist",
            text,
        )
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
