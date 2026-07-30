from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "029_add_ma_july_30_premarket.sql"
)
_VERIFY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_ma_july_30_premarket.sql"
)


class July30MastercardProfileTests(unittest.TestCase):
    def test_ma_seed_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn("'earnings:MA:2026Q2'", text)
        self.assertIn("'ma-2026q2-nongaap-eps-4pt77'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'DISABLED'", text)
        self.assertIn('"provider": "businesswire"', text)
        self.assertIn("'MIXED'", text)
        self.assertNotIn("'FULL_HTML_OR_PDF'", text)
        self.assertIn("'2026-07-30 13:00:00+00'", text)
        self.assertIn("0.999", text)
        self.assertIn("quantity = 100", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertNotIn("'ENABLED'", text)

    def test_ma_verifier_is_read_only(self) -> None:
        text = _VERIFY.read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("MA scope is not clean", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)


if __name__ == "__main__":
    unittest.main()
