from __future__ import annotations

import unittest
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "diagnose_july30_premarket.py"
)
_AUDIT = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "lightsail"
    / "JULY_30_PREMARKET_AUDIT_2026-07-30.md"
)


class DiagnoseJuly30PremarketTests(unittest.TestCase):
    def test_audit_is_read_only_and_redacts_failures(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("SET TRANSACTION READ ONLY", upper)
        self.assertIn("HIDE_PARAMETERS=TRUE", upper)
        self.assertIn("REDACT_SENSITIVE_TEXT", upper)
        self.assertNotIn("UPDATE ", upper)
        self.assertNotIn("DELETE ", upper)
        self.assertNotIn("INSERT ", upper)
        self.assertIn("INSPECT_ORDERS", upper)
        self.assertNotIn('"ORDER_ID":', upper)
        self.assertNotIn('"ACCOUNT_NAME":', upper)

    def test_audit_covers_all_july_30_profiles(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")

        for ticker in ("virt", "ci", "yum", "ice", "ma"):
            self.assertIn(f"earnings-{ticker}-2026q2", text)

    def test_audit_records_source_and_execution_boundaries(self) -> None:
        text = _AUDIT.read_text(encoding="utf-8")

        self.assertIn("SEC Latest Filings RSS/Atom", text)
        self.assertIn("CI | 28 ms | 60 ms", text)
        self.assertIn("MA | SEC CIK submissions polling", text)
        self.assertIn("public trading signals: 0", text)
        self.assertIn("UnexpectedResponseError", text)


if __name__ == "__main__":
    unittest.main()
