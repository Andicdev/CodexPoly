from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from tools.encrypt_trading_account_key import (
    MASTER_KEY_NAME,
    TradingAccountKeyEncryptionError,
    encrypt_trading_account_key,
)


_TEST_PRIVATE_KEY = "0x" + ("3" * 64)
_SECOND_PRIVATE_KEY = "0x" + ("4" * 64)


class EncryptTradingAccountKeyToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_directory = (
            Path(self.temporary_directory.name) / "account-secrets"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_generates_canonical_account_secret_file(self) -> None:
        prompts = iter((_TEST_PRIVATE_KEY, _TEST_PRIVATE_KEY))

        master_path, encrypted_path = encrypt_trading_account_key(
            self.output_directory,
            account_name="kinderSman",
            secret_reader=lambda _prompt: next(prompts),
        )

        self.assertEqual(master_path.name, MASTER_KEY_NAME)
        self.assertEqual(
            encrypted_path.name,
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_KINDERSMAN",
        )
        decrypted = Fernet(master_path.read_bytes()).decrypt(
            encrypted_path.read_bytes()
        ).decode("utf-8")
        self.assertEqual(decrypted, _TEST_PRIVATE_KEY)
        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(master_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(encrypted_path.stat().st_mode),
                0o600,
            )

    def test_auto_mode_reuses_master_key_for_multiple_accounts(
        self,
    ) -> None:
        first_prompts = iter((_TEST_PRIVATE_KEY, _TEST_PRIVATE_KEY))
        master_path, first_encrypted_path = (
            encrypt_trading_account_key(
                self.output_directory,
                account_name="kinderSman",
                secret_reader=lambda _prompt: next(first_prompts),
            )
        )
        original_master = master_path.read_bytes()

        second_prompts = iter(
            (_SECOND_PRIVATE_KEY, _SECOND_PRIVATE_KEY)
        )
        reused_master_path, second_encrypted_path = (
            encrypt_trading_account_key(
                self.output_directory,
                account_name="sport-two",
                secret_reader=lambda _prompt: next(second_prompts),
            )
        )

        self.assertEqual(reused_master_path, master_path)
        self.assertEqual(master_path.read_bytes(), original_master)
        self.assertEqual(
            second_encrypted_path.name,
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_SPORT_TWO",
        )
        self.assertEqual(
            Fernet(original_master).decrypt(
                first_encrypted_path.read_bytes()
            ).decode("utf-8"),
            _TEST_PRIVATE_KEY,
        )
        self.assertEqual(
            Fernet(original_master).decrypt(
                second_encrypted_path.read_bytes()
            ).decode("utf-8"),
            _SECOND_PRIVATE_KEY,
        )

    def test_accepts_confirmed_existing_master_key(self) -> None:
        supplied_master_key = Fernet.generate_key()
        prompts = iter(
            (
                supplied_master_key.decode("ascii"),
                supplied_master_key.decode("ascii"),
                _TEST_PRIVATE_KEY,
                _TEST_PRIVATE_KEY,
            )
        )

        master_path, encrypted_path = encrypt_trading_account_key(
            self.output_directory,
            account_name="kinderSman",
            master_key_mode="prompt",
            secret_reader=lambda _prompt: next(prompts),
        )

        self.assertEqual(master_path.read_bytes(), supplied_master_key)
        decrypted = Fernet(supplied_master_key).decrypt(
            encrypted_path.read_bytes()
        ).decode("utf-8")
        self.assertEqual(decrypted, _TEST_PRIVATE_KEY)

    def test_rejects_invalid_master_key_without_files(self) -> None:
        prompts = iter(("invalid", "invalid"))

        with self.assertRaisesRegex(
            TradingAccountKeyEncryptionError,
            "invalid-master-key",
        ):
            encrypt_trading_account_key(
                self.output_directory,
                account_name="kinderSman",
                master_key_mode="prompt",
                secret_reader=lambda _prompt: next(prompts),
            )

        self.assertEqual(
            list(self.output_directory.iterdir()),
            [],
        )

    def test_refuses_to_overwrite_one_account_secret(self) -> None:
        prompts = iter((_TEST_PRIVATE_KEY, _TEST_PRIVATE_KEY))
        encrypt_trading_account_key(
            self.output_directory,
            account_name="kinderSman",
            secret_reader=lambda _prompt: next(prompts),
        )

        with self.assertRaisesRegex(
            TradingAccountKeyEncryptionError,
            "account-secret-already-exists",
        ):
            encrypt_trading_account_key(
                self.output_directory,
                account_name="KINDERSMAN",
                secret_reader=lambda _prompt: self.fail(
                    "duplicate detection must happen before prompting"
                ),
            )


if __name__ == "__main__":
    unittest.main()
