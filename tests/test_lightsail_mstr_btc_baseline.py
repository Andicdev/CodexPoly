from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_DIRECTORY = _ROOT / "deploy" / "lightsail" / "mstr_btc"


class LightsailMstrBtcBaselineTests(unittest.TestCase):
    def test_seed_is_exact_idempotent_and_does_not_arm_trading(self) -> None:
        text = (
            _DIRECTORY / "001_seed_jul20_baseline.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("843775", text)
        self.assertIn("0001193125-26-308369", text)
        self.assertIn("2026-07-20 12:00:16+00", text)
        self.assertIn("IF FOUND THEN", text)
        self.assertIn("IS DISTINCT FROM", text)
        self.assertNotIn("resolution_execution_profiles", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)

    def test_verifier_is_read_only_and_pins_both_timestamps(self) -> None:
        text = (
            _DIRECTORY / "002_verify_jul21_27_baseline.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("ROLLBACK", text)
        self.assertIn("as_of < TIMESTAMPTZ", text)
        self.assertIn("observed_at < TIMESTAMPTZ", text)
        self.assertIn("2026-07-21 04:00:00+00", text)
        self.assertIn(
            "trg_mstr_btc_holdings_state_append_only",
            text,
        )
        self.assertIn("resolution_execution_profiles", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("scope_id LIKE 'mstr-btc:%'", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)


if __name__ == "__main__":
    unittest.main()
