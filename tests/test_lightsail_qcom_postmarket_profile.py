from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "023_add_qcom_july_29_postmarket.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_qcom_july_29_postmarket.sql"
)
_ARM = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "024_arm_qcom_july_29_postmarket.sql"
)
_ARMED_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_qcom_july_29_auto_live_armed.sql"
)


class QualcommPostmarketProfileSqlTests(unittest.TestCase):
    def test_seed_is_qcom_only_and_non_live(self) -> None:
        text = _SEED.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'earnings:QCOM:2026Q3'", text)
        for ticker in ("MSFT", "META", "EBAY", "HOOD", "SBUX"):
            self.assertNotIn(f"'earnings:{ticker}:", text)

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

    def test_seed_declares_three_source_paths(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertIn('"provider": "sec_api"', text)
        self.assertIn('"provider": "sec"', text)
        self.assertIn('"provider": "company_ir"', text)
        self.assertIn('"kind": "direct_document"', text)
        self.assertIn(
            (
                "https://s204.q4cdn.com/645488518/files/"
                "doc_financials/2026/q3/"
                "FY2026-3rd-Quarter-Earnings-Release.pdf"
            ),
            text,
        )

    def test_check_is_read_only_and_fail_closed(self) -> None:
        text = _CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("'AUTO_LIVE'", text)
        self.assertIn("FACTS OR CLAIMS ALREADY EXIST", upper)
        self.assertNotIn("SELECT *", upper)

    def test_arm_is_guarded_and_never_enables_profile(self) -> None:
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

    def test_armed_check_is_read_only_and_time_aware(self) -> None:
        text = _ARMED_CHECK.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("ROLLBACK", upper)
        self.assertIn("SCHEDULE_STATE <> 'PENDING'", upper)
        self.assertIn("SCHEDULE_STATE <> 'READY'", upper)
        self.assertIn("PROFILE_STATE <> 'DISABLED'", upper)
        self.assertIn("READINESS_UNTIL", upper)
        self.assertIn("TRADING_ENABLED", upper)
        self.assertIn("SUPERVISION_ENABLED", upper)
        self.assertIn("FACTS OR CLAIMS ALREADY EXIST", upper)
        self.assertNotIn("SELECT *", upper)


if __name__ == "__main__":
    unittest.main()
