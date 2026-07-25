from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from scripts.install_single_account_secrets import (
    ENCRYPTED_KEY_NAME,
    INSTALLED_SECRET_NAMES,
    MASTER_KEY_NAME,
    AccountSecretInstallError,
    install_single_account_secrets,
)


_TEST_PRIVATE_KEY = "0x" + ("1" * 64)


class InstallSingleAccountSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.secret_directory = (
            Path(self.temporary_directory.name) / "secrets"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_installs_fresh_pair_without_returning_values(self) -> None:
        prompts = iter((_TEST_PRIVATE_KEY, _TEST_PRIVATE_KEY))

        result = install_single_account_secrets(
            self.secret_directory,
            secret_reader=lambda _prompt: next(prompts),
            require_root=False,
        )

        self.assertEqual(result, INSTALLED_SECRET_NAMES)
        master_path = self.secret_directory / MASTER_KEY_NAME
        encrypted_path = self.secret_directory / ENCRYPTED_KEY_NAME
        self.assertTrue(master_path.is_file())
        self.assertTrue(encrypted_path.is_file())
        self.assertFalse(master_path.is_symlink())
        self.assertFalse(encrypted_path.is_symlink())
        decrypted = Fernet(master_path.read_bytes()).decrypt(
            encrypted_path.read_bytes()
        ).decode("utf-8")
        self.assertEqual(decrypted, _TEST_PRIVATE_KEY)
        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(master_path.stat().st_mode),
                0o444,
            )
            self.assertEqual(
                stat.S_IMODE(encrypted_path.stat().st_mode),
                0o444,
            )

    def test_refuses_replacement(self) -> None:
        self.secret_directory.mkdir(mode=0o700)
        existing = self.secret_directory / MASTER_KEY_NAME
        existing.write_text("existing", encoding="utf-8")

        with self.assertRaisesRegex(
            AccountSecretInstallError,
            "account-secret-already-exists",
        ):
            install_single_account_secrets(
                self.secret_directory,
                secret_reader=lambda _prompt: _TEST_PRIVATE_KEY,
                require_root=False,
            )

        self.assertFalse(
            (self.secret_directory / ENCRYPTED_KEY_NAME).exists()
        )

    def test_rejects_mismatched_confirmation_without_files(self) -> None:
        prompts = iter((_TEST_PRIVATE_KEY, "0x" + ("2" * 64)))

        with self.assertRaisesRegex(
            AccountSecretInstallError,
            "private-key-mismatch",
        ):
            install_single_account_secrets(
                self.secret_directory,
                secret_reader=lambda _prompt: next(prompts),
                require_root=False,
            )

        for name in INSTALLED_SECRET_NAMES:
            self.assertFalse((self.secret_directory / name).exists())

    def test_rejects_invalid_private_key_without_files(self) -> None:
        with self.assertRaisesRegex(
            AccountSecretInstallError,
            "invalid-private-key-format",
        ):
            install_single_account_secrets(
                self.secret_directory,
                secret_reader=lambda _prompt: "invalid",
                require_root=False,
            )

        for name in INSTALLED_SECRET_NAMES:
            self.assertFalse((self.secret_directory / name).exists())


if __name__ == "__main__":
    unittest.main()
