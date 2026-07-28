from __future__ import annotations

import unittest
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "diagnose_live_order_status.py"
)


class LiveOrderStatusDiagnosticTests(unittest.TestCase):
    def test_script_is_read_only(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn("READ_ONLY_ORDER_INSPECTION", text)
        self.assertIn("gateway.inspect_orders(", text)
        self.assertIn('"orders_changed": False', text)
        self.assertNotIn("gateway.cancel_orders(", text)
        self.assertNotIn("gateway.place_replacement(", text)
        self.assertNotIn("executor.execute(", text)


if __name__ == "__main__":
    unittest.main()
