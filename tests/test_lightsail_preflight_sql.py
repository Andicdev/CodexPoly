from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PREFLIGHT = _ROOT / "deploy" / "lightsail" / "preflight"


class LightsailPreflightSqlTests(unittest.TestCase):
    def test_enable_is_guarded_to_one_exact_disabled_profile(self) -> None:
        text = (
            _PREFLIGHT
            / "001_enable_nvts_authenticated_preflight.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("another execution profile is already enabled", text)
        self.assertIn("profile_key = 'earnings-nvts-2026q2'", text)
        self.assertIn("account_name = 'abccbaq'", text)
        self.assertIn("status = 'DISABLED'", text)
        self.assertIn("changed_rows <> 1", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)

    def test_verifier_is_read_only_and_requires_one_profile(self) -> None:
        text = (
            _PREFLIGHT
            / "002_verify_nvts_authenticated_preflight.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("ROLLBACK", text)
        self.assertIn("expected exactly one enabled in-window profile", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("DELETE FROM", text)

    def test_restore_disables_and_restores_checked_in_window(self) -> None:
        text = (
            _PREFLIGHT
            / "003_restore_nvts_after_preflight.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("status = 'DISABLED'", text)
        self.assertIn("2026-07-27 19:00:00+00", text)
        self.assertIn("2026-07-28 03:00:00+00", text)
        self.assertIn("an execution profile remains enabled", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)


if __name__ == "__main__":
    unittest.main()
