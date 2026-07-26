from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PREFLIGHT = (
    _ROOT / "deploy" / "lightsail" / "mstr_btc" / "preflight"
)


class LightsailMstrBtcPreflightSqlTests(unittest.TestCase):
    def test_each_enable_is_single_profile_claim_guarded_and_safe(
        self,
    ) -> None:
        enable_paths = sorted(_PREFLIGHT.glob("00[1-3]_enable_*.sql"))

        self.assertEqual(len(enable_paths), 3)
        for path in enable_paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "another execution profile is already enabled",
                text,
            )
            self.assertIn(
                "an MSTR execution claim already exists",
                text,
            )
            self.assertIn("status = 'DISABLED'", text)
            self.assertIn("changed_rows <> 1", text)
            self.assertIn(
                "expected exactly one enabled in-window profile",
                text,
            )
            self.assertNotIn("DELETE FROM", text)
            self.assertNotIn("DROP TABLE", text)
            self.assertNotIn("INSERT INTO", text)

    def test_enable_files_cover_exactly_three_profile_keys(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(
                _PREFLIGHT.glob("00[1-3]_enable_*.sql")
            )
        )

        self.assertEqual(
            text.count("profile_key = 'mstr-jul21-27-purchase-any'"),
            1,
        )
        self.assertEqual(
            text.count(
                "profile_key = 'mstr-jul21-27-purchase-over-1000'"
            ),
            1,
        )
        self.assertEqual(
            text.count("profile_key = 'mstr-jul21-27-sale-any'"),
            1,
        )

    def test_restore_disables_all_three_and_restores_window(self) -> None:
        text = (
            _PREFLIGHT / "004_restore_all_disabled.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("status = 'DISABLED'", text)
        self.assertIn("changed_rows <> 3", text)
        self.assertIn("2026-07-27 06:00:00+00", text)
        self.assertIn("2026-07-28 04:00:00+00", text)
        self.assertIn("an execution profile remains enabled", text)
        self.assertIn(
            "an MSTR execution claim exists after preflight",
            text,
        )
        self.assertNotIn("DELETE FROM", text)
        self.assertNotIn("DROP TABLE", text)


if __name__ == "__main__":
    unittest.main()
