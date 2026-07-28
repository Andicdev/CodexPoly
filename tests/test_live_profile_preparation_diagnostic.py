from __future__ import annotations

import unittest
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "diagnose_live_profile_preparation.py"
)


class LiveProfilePreparationDiagnosticTests(unittest.TestCase):
    def test_script_is_prepare_only(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn("NO_SUBMIT_LIVE_PREPARATION", text)
        self.assertIn("executor.prepare(", text)
        self.assertIn('"order_submitted": False', text)
        self.assertIn('"claim_reserved": False', text)
        self.assertNotIn("executor.execute(", text)
        self.assertNotIn(".post_orders(", text)
        self.assertNotIn(".reserve_many(", text)
        self.assertNotIn("encrypted_private_key", text)


if __name__ == "__main__":
    unittest.main()
