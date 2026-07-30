from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "032_add_aapl_july_30_postmarket.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_aapl_july_30_postmarket.sql"
)
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "038_arm_aapl_july_30_postmarket.sql"
)
_ARMED_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_aapl_july_30_auto_live_armed.sql"
)


class ApplePostmarketProfileSqlTests(unittest.TestCase):
    def test_seed_is_aapl_only_and_non_live(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings:AAPL:2026Q3'", text)
        self.assertIn("'aapl-2026q3-gaap-eps-1pt89'", text)
        self.assertIn("'DISABLED'", text)
        self.assertNotIn("'ENABLED'", text)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("'POST_MARKET'", text)
        self.assertIn("quantity = 100", text)
        self.assertIn("0.999", text)
        self.assertIn("reviewed_notional <> 99.9", text)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_seed_uses_release_floor_not_conference_call(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn(
            "TIMESTAMPTZ '2026-07-30 20:30:00+00'",
            text,
        )
        self.assertIn(
            "TIMESTAMPTZ '2026-07-30 21:00:00+00'",
            text,
        )
        self.assertIn(
            "TIMESTAMPTZ '2026-07-30 18:30:00+00'",
            text,
        )
        self.assertIn("'HISTORICAL_PATTERN'", text)
        self.assertIn("timing_contract_version", text)
        self.assertIn("7200", text)
        self.assertIn("activate_at <= earliest_signal_at", text)

    def test_seed_declares_parallel_source_paths(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn('"provider": "sec_api"', text)
        self.assertIn('"provider": "sec_current"', text)
        self.assertIn('"provider": "sec_latest"', text)
        self.assertIn(
            "https://www.apple.com/newsroom/rss-feed.rss",
            text,
        )
        self.assertIn('"provider": "company_ir"', text)
        self.assertNotIn('"press_wire"', text)

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("TRADING STATE", upper)
        self.assertIn("TIMING_CONTRACT_VERSION = 1", upper)
        self.assertNotIn("SELECT *", upper)

    def test_arm_changes_only_reviewed_schedule_mode(self) -> None:
        text = _ARM.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn(
            "TIMESTAMPTZ '2026-07-30 18:15:00+00'",
            text,
        )
        self.assertIn(
            "TIMESTAMPTZ '2026-07-30 18:30:00+00'",
            text,
        )
        self.assertIn("timing_contract_version = 1", text)
        self.assertIn("supervision_enabled", text)
        self.assertIn("trading_enabled", text)
        self.assertIn("reviewed_notional <> 99.9", text)
        self.assertIn("'armed_for_live', true", text)
        self.assertNotIn("SET STATUS = 'ENABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("DROP TABLE", upper)

    def test_armed_check_is_read_only_and_fail_closed(self) -> None:
        text = _ARMED_CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("'AUTO_LIVE'", text)
        self.assertIn("PROFILE_STATE <> 'DISABLED'", upper)
        self.assertIn("SCHEDULE_STATE IS NULL", upper)
        self.assertIn("SCHEDULE_STATE <> 'PENDING'", upper)
        self.assertIn("SCHEDULE_STATE <> 'READY'", upper)
        self.assertIn("READINESS_CHECKED IS NULL", upper)
        self.assertIn("READINESS_UNTIL IS NULL", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("EARNINGS_FACT_CANDIDATES", upper)
        self.assertIn("RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("UPDATE ", upper)
        self.assertNotIn("DELETE FROM", upper)


if __name__ == "__main__":
    unittest.main()
