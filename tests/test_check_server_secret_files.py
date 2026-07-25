from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.check_server_secret_files import build_report


class CheckServerSecretFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "environments": {
                        "staging": {
                            "worker": ["DATABASE_URL_SERVER_INT", "API_KEY"]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.root / "secrets" / "staging").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reports_names_only_as_present_or_missing(self) -> None:
        secret_file = (
            self.root / "secrets" / "staging" / "DATABASE_URL_SERVER_INT"
        )
        secret_file.write_text("do-not-print-this-value", encoding="utf-8")
        if os.name == "posix":
            secret_file.chmod(0o400)

        report = build_report(
            self.manifest,
            self.root / "secrets",
            environment="staging",
            expected_owner_uid=(
                os.geteuid() if hasattr(os, "geteuid") else None
            ),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["present_keys"],
            ["DATABASE_URL_SERVER_INT"],
        )
        self.assertEqual(report["missing_keys"], ["API_KEY"])
        self.assertNotIn("do-not-print-this-value", json.dumps(report))

    def test_rejects_symlink(self) -> None:
        source = self.root / "source"
        source.write_text("value", encoding="utf-8")
        link = self.root / "secrets" / "staging" / "API_KEY"
        try:
            link.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")

        report = build_report(
            self.manifest,
            self.root / "secrets",
            environment="staging",
            service="worker",
            expected_owner_uid=(
                os.geteuid() if hasattr(os, "geteuid") else None
            ),
        )

        self.assertIn("API_KEY", report["missing_keys"])


if __name__ == "__main__":
    unittest.main()
