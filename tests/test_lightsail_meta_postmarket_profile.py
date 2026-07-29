from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "021_add_meta_july_29_postmarket.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_meta_july_29_postmarket.sql"
)
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "022_arm_meta_july_29_postmarket.sql"
)


class MetaPostmarketProfileSqlTests(unittest.TestCase):
    def test_seed_is_meta_only_and_non_live(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings:META:2026Q2'", text)
        for ticker in ("QCOM", "MSFT", "EBAY", "HOOD", "SBUX"):
            self.assertNotIn(f"'earnings:{ticker}:", text)

        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'POST_MARKET'", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("0.999", text)
        self.assertIn("reviewed_notional <> 99.9", text)
        self.assertIn("execution claim must not exist", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_declares_three_independent_source_paths(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn('"provider": "sec_api"', text)
        self.assertIn('"provider": "sec"', text)
        self.assertIn(
            "https://investor.atmeta.com/rss/pressrelease.aspx",
            text,
        )
        self.assertIn('"provider": "company_ir"', text)
        self.assertIn(
            "https://www.prnewswire.com/rss/news-releases-list.rss",
            text,
        )
        self.assertIn('"provider": "prnewswire"', text)
        self.assertIn('"title_none": ["to announce"]', text)

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("FACTS OR CLAIMS ALREADY EXIST", upper)
        self.assertNotIn("SELECT *", upper)

    def test_arm_is_guarded_and_does_not_enable_profile(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("SCHEDULE_STATE <> 'READY'", upper)
        self.assertIn("READINESS_UNTIL", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertIn("REVIEWED_NOTIONAL <> 99.9", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)


if __name__ == "__main__":
    unittest.main()
