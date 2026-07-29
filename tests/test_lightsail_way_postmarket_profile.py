from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT / "deploy" / "lightsail" / "seeds"
    / "026_add_way_july_29_postmarket.sql"
)
_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_way_july_29_postmarket.sql"
)
_ARM = (
    _ROOT / "deploy" / "lightsail" / "live"
    / "030_arm_way_july_29_postmarket.sql"
)
_ARMED_CHECK = (
    _ROOT / "deploy" / "lightsail" / "checks"
    / "verify_way_july_29_auto_live_armed.sql"
)


class WaystarPostmarketProfileSqlTests(unittest.TestCase):
    def test_seed_is_way_only_and_non_live(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings:WAY:2026Q2'", text)
        self.assertIn(
            "'way-2026q2-nongaap-eps-0pt40'",
            text,
        )
        for ticker in ("QCOM", "MSFT", "META", "EA", "HOOD"):
            self.assertNotIn(f"'earnings:{ticker}:", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("reviewed_notional <> 99.9", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_declares_all_source_paths(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn('"provider": "sec_api"', text)
        self.assertIn('"provider": "sec"', text)
        self.assertIn('"provider": "company_ir"', text)
        self.assertIn('"provider": "prnewswire"', text)
        self.assertIn(
            "https://investors.waystar.com/rss/news-releases.xml",
            text,
        )
        self.assertIn("'CONFIRMED'", text)

    def test_checks_are_read_only_and_fail_closed(self) -> None:
        for path in (_CHECK, _ARMED_CHECK):
            text = path.read_text(encoding="utf-8")
            upper = text.upper()
            self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
            self.assertIn("ROLLBACK", upper)
            self.assertIn("FACTS OR CLAIMS", upper)
            self.assertNotIn("SELECT *", upper)

    def test_arm_is_guarded_and_never_enables_profile(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("SCHEDULE_STATE <> 'READY'", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertIn("REVIEWED_NOTIONAL <> 99.9", upper)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)


if __name__ == "__main__":
    unittest.main()
