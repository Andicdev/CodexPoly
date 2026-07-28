from __future__ import annotations

import unittest
from pathlib import Path


_SQL = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "lightsail"
    / "live"
    / "005_complete_resolved_premarket_profiles.sql"
)


class PremarketCompletionSqlTests(unittest.TestCase):
    def test_completion_is_guarded_and_leaves_orders_unchanged(self) -> None:
        text = _SQL.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("BEGIN;", upper)
        self.assertIn("COMMIT;", upper)
        self.assertIn("'EARNINGS-HLT-2026Q2'", upper)
        self.assertIn("'EARNINGS-RCL-2026Q2'", upper)
        self.assertIn("'EXECUTED'", upper)
        self.assertIn("'ACCEPTED_ORDER_LEFT_UNCHANGED'", upper)
        self.assertIn("AUTOMATION_MODE = 'MANUAL'", upper)
        self.assertIn("STATE = 'EXPIRED'", upper)
        self.assertIn("STATUS = 'DISABLED'", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)


if __name__ == "__main__":
    unittest.main()
