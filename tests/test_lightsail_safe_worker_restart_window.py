from __future__ import annotations

import unittest
from pathlib import Path


_CHECK = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_safe_worker_restart_window.sql"
)


class SafeWorkerRestartWindowTests(unittest.TestCase):
    def test_check_is_read_only_and_fail_closed(self) -> None:
        upper = _CHECK.read_text(encoding="utf-8").upper()

        self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
        self.assertIn("STATUS = 'ENABLED'", upper)
        self.assertIn("STATE = 'ACTIVE'", upper)
        self.assertIn("INTERVAL '15 MINUTES'", upper)
        self.assertIn("STATUS = 'PENDING'", upper)
        self.assertIn("STATUS IN ('ACTIVE', 'REPRICING')", upper)
        self.assertIn("ROLLBACK;", upper)
        self.assertNotIn("UPDATE ", upper)
        self.assertNotIn("INSERT ", upper)
        self.assertNotIn("DELETE ", upper)
        self.assertNotIn("CANCEL", upper)


if __name__ == "__main__":
    unittest.main()
