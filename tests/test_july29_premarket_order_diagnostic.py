from __future__ import annotations

import unittest
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "diagnose_july29_premarket_orders.py"
)


class July29PremarketOrderDiagnosticTests(unittest.TestCase):
    def test_database_only_mode_and_source_links_are_guarded(self) -> None:
        text = _SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'connection.execute(text("SET TRANSACTION READ ONLY"))',
            text,
        )
        self.assertIn('"--skip-remote"', text)
        self.assertIn("if not args.skip_remote:", text)
        self.assertIn("event.source_url", text)
        self.assertIn("event.filing_url", text)
        self.assertNotIn("gateway.cancel_orders(", text)
        self.assertNotIn("gateway.place_replacement(", text)
        self.assertNotIn("executor.execute(", text)


if __name__ == "__main__":
    unittest.main()
