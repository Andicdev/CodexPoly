from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cbr_trading.runtime_secrets import (
    RuntimeSecretError,
    read_runtime_secret,
    runtime_secret_present,
    trading_account_private_key_secret_name,
)


class RuntimeSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.secret_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_environment_is_local_fallback(self) -> None:
        value = read_runtime_secret(
            "API_KEY",
            environ={"API_KEY": "local-value"},
            secret_directory=self.secret_dir,
        )

        self.assertEqual(value, "local-value")

    def test_account_name_has_canonical_secret_suffix(self) -> None:
        self.assertEqual(
            trading_account_private_key_secret_name("kinderSman"),
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_KINDERSMAN",
        )
        self.assertEqual(
            trading_account_private_key_secret_name("sport-two"),
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_SPORT_TWO",
        )

    def test_conventional_file_wins_over_environment(self) -> None:
        (self.secret_dir / "API_KEY").write_text(
            "file-value\n",
            encoding="utf-8",
        )

        value = read_runtime_secret(
            "API_KEY",
            environ={"API_KEY": "environment-value"},
            secret_directory=self.secret_dir,
        )

        self.assertEqual(value, "file-value")

    def test_explicit_file_is_fail_closed_and_error_is_value_safe(self) -> None:
        missing_path = self.secret_dir / "missing-file"

        with self.assertRaises(RuntimeSecretError) as caught:
            read_runtime_secret(
                "API_KEY",
                environ={
                    "API_KEY": "must-not-fall-back",
                    "API_KEY_FILE": str(missing_path),
                },
            )

        error_text = str(caught.exception)
        self.assertIn("API_KEY", error_text)
        self.assertNotIn("must-not-fall-back", error_text)
        self.assertNotIn(str(missing_path), error_text)

    def test_presence_report_does_not_include_value(self) -> None:
        (self.secret_dir / "API_KEY").write_text(
            "value-that-must-not-be-reported",
            encoding="utf-8",
        )

        present = runtime_secret_present(
            "API_KEY",
            environ={},
            secret_directory=self.secret_dir,
        )

        report = json.dumps({"API_KEY": present})
        self.assertTrue(present)
        self.assertNotIn("value-that-must-not-be-reported", report)


if __name__ == "__main__":
    unittest.main()
