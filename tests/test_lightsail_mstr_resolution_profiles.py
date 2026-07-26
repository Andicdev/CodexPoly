from __future__ import annotations

import unittest
from pathlib import Path

from cbr_trading.mstr_btc import mstr_jul21_27_market_bindings


_ROOT = Path(__file__).resolve().parents[1]
_MSTR_DEPLOY = _ROOT / "deploy" / "lightsail" / "mstr_btc"
_SEED = _MSTR_DEPLOY / "004_seed_disabled_resolution_profiles.sql"
_VERIFY = (
    _MSTR_DEPLOY / "005_verify_disabled_resolution_profiles.sql"
)


class LightsailMstrResolutionProfileTests(unittest.TestCase):
    def test_seed_contains_exact_checked_in_market_bindings(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        for binding in mstr_jul21_27_market_bindings():
            self.assertIn(binding.signal_id, text)
            self.assertIn(binding.condition_id, text)
            self.assertIn(binding.source_reference, text)

    def test_seed_is_guarded_and_keeps_every_profile_disabled(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertIn("BEGIN;", statements)
        self.assertIn("COMMIT;", statements)
        self.assertIn(
            "LOCK TABLE RESOLUTION_EXECUTION_PROFILES",
            statements,
        )
        self.assertEqual(
            text.count("'mstr_btc_resolution'"),
            6,
        )
        self.assertEqual(text.count("'DISABLED'"), 5)
        self.assertNotIn("SET status = 'ENABLED'", text)
        self.assertNotIn("DELETE FROM", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertNotIn("TRUNCATE", statements)
        self.assertIn("0.999", text)
        self.assertIn("0.01", text)
        self.assertIn("0.001", text)

    def test_read_only_invariant_checks_profiles_and_no_claims(self) -> None:
        text = _VERIFY.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK;", upper)
        self.assertIn("RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertIn("STATUS = 'ENABLED'", upper)
        self.assertNotIn("INSERT INTO", upper)
        self.assertNotIn("UPDATE ", upper)
        self.assertNotIn("DELETE FROM", upper)


if __name__ == "__main__":
    unittest.main()
