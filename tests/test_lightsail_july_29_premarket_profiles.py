from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "018_add_july_29_premarket_profiles.sql"
)
_BOOTSTRAP = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "020_bootstrap_july_29_premarket_profiles.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_premarket_profiles.sql"
)
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "018_arm_july_29_premarket_live_block.sql"
)
_ARMED_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_premarket_auto_live_armed.sql"
)
_READY_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_premarket_preflight_ready.sql"
)
_ACTIVE_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_premarket_live_active.sql"
)


class July29PremarketProfileSqlTests(unittest.TestCase):
    def test_production_bootstrap_is_premarket_only_and_non_live(self) -> None:
        text = _BOOTSTRAP.read_text(encoding="utf-8")
        upper = text.upper()

        for ticker in ("SOFI", "PG", "HUM"):
            self.assertIn(f"'earnings:{ticker}:2026Q", text)
        for ticker in ("QCOM", "MSFT", "META", "EBAY", "HOOD"):
            self.assertNotIn(f"'earnings:{ticker}:", text)

        self.assertIn("'PRE_MARKET'", text)
        self.assertNotIn("'POST_MARKET'", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("EXECUTION CLAIM MUST NOT EXIST", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_is_disabled_and_auto_preflight_only(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        for ticker in ("WING", "ARCC", "IART", "GRMN", "CBRE", "PAG"):
            self.assertIn(f"'earnings:{ticker}:2026Q2'", text)
        for ticker in ("SOFI", "PG", "HUM"):
            self.assertIn(f"'earnings-{ticker.lower()}-", text)

        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'2026-07-29-pre-market'", text)
        self.assertIn("TIMESTAMPTZ '2026-07-29 09:00:00+00'", text)
        self.assertIn("TIMESTAMPTZ '2026-07-29 17:00:00+00'", text)
        self.assertIn("'abccbaq'", text)
        self.assertIn("0.999", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("reviewed_notional > 1000", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_declares_reviewed_public_transports(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        for endpoint in (
            "https://ir.wingstop.com/feed/",
            "https://investor.integralife.com/rss/news-releases.xml",
            "https://www.garmin.com/en-US/newsroom/feed/",
            "https://ir.cbre.com/press-releases/rss",
            "https://humana.gcs-web.com/rss/news-releases.xml",
            "https://www.prnewswire.com/rss/news-releases-list.rss",
            (
                "https://feed.businesswire.com/rss/home/"
                "?rss=G1QFDERJXkJeGVtQWw=="
            ),
        ):
            self.assertIn(endpoint, text)
        self.assertIn('"provider": "globenewswire"', text)
        self.assertIn('"provider": "businesswire"', text)
        self.assertIn('"provider": "sec_api"', text)
        self.assertIn('"provider": "sec"', text)

    def test_fail_closed_check_is_read_only(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("AUTO_PREFLIGHT", upper)
        self.assertNotIn("AUTO_LIVE", upper)
        self.assertIn("EXECUTION CLAIM MUST NOT EXIST", upper)
        self.assertIn("JULY 29 PRE-MARKET PROFILE SET MISMATCH", upper)
        self.assertNotIn("SELECT *", upper)

    def test_live_arm_is_guarded_and_does_not_enable_profiles(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        for ticker in (
            "SOFI",
            "PG",
            "HUM",
            "WING",
            "ARCC",
            "IART",
            "GRMN",
            "CBRE",
            "PAG",
        ):
            self.assertIn(f"'earnings:{ticker}:2026Q", text)
        for ticker in ("QCOM", "MSFT", "META", "EBAY", "HOOD", "SBUX"):
            self.assertNotIn(f"'earnings:{ticker}:", text)

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("REVIEWED_NOTIONAL <> 899.1", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertNotIn("STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_armed_check_is_read_only_and_fail_closed(self) -> None:
        text = _ARMED_CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("FRESH FULLY-LIVE RESOLUTION HEARTBEAT", upper)
        self.assertIn("FACTS OR CLAIMS ALREADY EXIST", upper)
        self.assertNotIn("SELECT *", upper)

    def test_ready_and_active_checks_are_read_only(self) -> None:
        ready = _READY_CHECK.read_text(encoding="utf-8")
        active = _ACTIVE_CHECK.read_text(encoding="utf-8")

        for text in (ready, active):
            upper = text.upper()
            self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
            self.assertIn("ROLLBACK", upper)
            self.assertIn("READINESS_EVIDENCE <> '{}'::JSONB", upper)
            self.assertIn("FRESH FULLY-LIVE RESOLUTION HEARTBEAT", upper)
            self.assertIn("FACTS OR CLAIMS ALREADY EXIST", upper)
            self.assertNotIn("SELECT *", upper)

        self.assertIn("schedule.state = 'READY'", ready)
        self.assertIn("profile.status = 'DISABLED'", ready)
        self.assertIn("schedule.state = 'ACTIVE'", active)
        self.assertIn("profile.status = 'ENABLED'", active)
        self.assertIn("active_notional <> 899.1", active)


if __name__ == "__main__":
    unittest.main()
