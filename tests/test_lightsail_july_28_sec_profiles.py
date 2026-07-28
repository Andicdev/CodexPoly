from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "008_add_july_28_sec_profiles.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_28_sec_profiles.sql"
)


class LightsailJuly28SecProfilesTests(unittest.TestCase):
    def test_seed_is_idempotent_with_ford_ir_and_disarmed(self) -> None:
        text = _SEED.read_text(encoding="utf-8").lower()

        self.assertEqual(
            text.count("'disabled'"),
            2,
        )
        self.assertIn("on conflict (rule_key) do update", text)
        self.assertIn("on conflict (profile_key) do update", text)
        self.assertIn("where resolution_execution_profiles.status", text)
        self.assertIn("'shadow'", text)
        self.assertNotIn("'enabled'", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)
        self.assertNotIn("drop table", text)
        self.assertEqual(text.count("'company_ir'"), 2)
        self.assertIn("'direct_document'", text)
        self.assertIn("'s205.q4cdn.com'", text)
        self.assertNotIn("'press_wire'", text)

        for ticker in (
            "pypl",
            "ups",
            "hlt",
            "ivz",
            "ko",
            "jblu",
            "spgi",
            "sbux",
            "v",
            "f",
        ):
            self.assertIn(f"'earnings-{ticker}-2026q", text)

    def test_check_is_read_only_and_requires_no_claim(self) -> None:
        text = _CHECK.read_text(encoding="utf-8").lower()

        self.assertIn("status = 'disabled'", text)
        self.assertIn(
            "july earnings sec execution claim must not exist",
            text,
        )
        self.assertIn(") <> 10", text)
        self.assertNotIn("insert into", text)
        self.assertNotIn("update ", text)
        self.assertNotIn("delete from", text)


if __name__ == "__main__":
    unittest.main()
