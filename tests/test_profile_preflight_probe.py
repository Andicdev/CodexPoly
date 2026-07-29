from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PROBE = _ROOT / "scripts" / "profile_preflight_probe.py"


class ProfilePreflightProbeTests(unittest.TestCase):
    def test_probe_is_non_submitting_and_sanitized(self) -> None:
        text = _PROBE.read_text(encoding="utf-8")

        self.assertIn("PolymarketPreflightPreparedExecutor", text)
        self.assertIn('"order_submitted": False', text)
        self.assertIn('"executor_execute_called": False', text)
        self.assertIn("redact_exception(exc)", text)
        self.assertNotIn(".execute(", text)
        self.assertNotIn("PolymarketPreparedExecutor(", text)


if __name__ == "__main__":
    unittest.main()
