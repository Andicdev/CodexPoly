from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbr_trading.live.account_repository import (
    RuntimeSecretTradingAccountRepository,
    SqlAlchemyTradingAccountRepository,
    TradingAccountLoadError,
    build_trading_account_repository,
    normalize_account_rows,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "name": "kinderSman",
        "wallet_address": "0x1234567890abcdef1234567890abcdef1234abcd",
        "venue": "polymarket_clob",
        "is_active": True,
        "pk_enc": b"encrypted",
        "signature_type": 2,
    }
    row.update(overrides)
    return row


class TradingAccountNormalizationTests(unittest.TestCase):
    def test_accepts_case_different_stored_name(self) -> None:
        account = normalize_account_rows(
            [_row(pk_enc=memoryview(b"encrypted"))],
            requested="KinderSman",
        )

        self.assertEqual(account.name, "kinderSman")
        self.assertEqual(account.signature_type, 2)
        self.assertEqual(
            account.encrypted_private_key,
            b"encrypted",
        )
        self.assertEqual(account.wallet_masked, "0x1234...abcd")
        self.assertNotIn("encrypted", repr(account))

    def test_missing_account_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "not found",
        ):
            normalize_account_rows([], requested="missing")

    def test_case_insensitive_duplicates_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "Multiple",
        ):
            normalize_account_rows(
                [_row(), _row(name="KinderSMan")],
                requested="kindersman",
            )

    def test_inactive_or_keyless_account_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "inactive",
        ):
            normalize_account_rows(
                [_row(is_active=False)],
                requested="kinderSman",
            )

        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "encrypted private key",
        ):
            normalize_account_rows(
                [_row(pk_enc=None)],
                requested="kinderSman",
            )


class RuntimeSecretTradingAccountRepositoryTests(unittest.TestCase):
    def test_loads_one_account_from_file_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "account-key"
            secret_path.write_text(
                "encrypted-private-key",
                encoding="utf-8",
            )
            repository = (
                RuntimeSecretTradingAccountRepository.from_env(
                    {
                        "TRADING_ACCOUNT_NAME": "abccbaq",
                        "TRADING_ACCOUNT_WALLET_ADDRESS": (
                            "0x1234567890abcdef1234567890abcdef1234abcd"
                        ),
                        "TRADING_ACCOUNT_VENUE": "polymarket_clob",
                        "TRADING_ACCOUNT_SIGNATURE_TYPE": "2",
                        "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_FILE": (
                            str(secret_path)
                        ),
                    }
                )
            )

        account = repository.load_active("ABCCBAQ")

        self.assertEqual(account.name, "abccbaq")
        self.assertEqual(account.venue, "polymarket_clob")
        self.assertEqual(account.signature_type, 2)
        self.assertEqual(
            account.encrypted_private_key,
            b"encrypted-private-key",
        )
        self.assertNotIn("encrypted-private-key", repr(repository))

    def test_rejects_another_account_name(self) -> None:
        repository = RuntimeSecretTradingAccountRepository.from_env(
            {
                "TRADING_ACCOUNT_NAME": "abccbaq",
                "TRADING_ACCOUNT_WALLET_ADDRESS": (
                    "0x1234567890abcdef1234567890abcdef1234abcd"
                ),
                "TRADING_ACCOUNT_SIGNATURE_TYPE": "2",
                "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED": "encrypted",
            }
        )

        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "not found",
        ):
            repository.load_active("another")

    def test_missing_single_account_key_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "encrypted private key",
        ):
            RuntimeSecretTradingAccountRepository.from_env(
                {
                    "TRADING_ACCOUNT_NAME": "abccbaq",
                    "TRADING_ACCOUNT_WALLET_ADDRESS": (
                        "0x1234567890abcdef1234567890abcdef1234abcd"
                    ),
                    "TRADING_ACCOUNT_SIGNATURE_TYPE": "2",
                }
            )

    def test_missing_single_account_name_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "name is empty",
        ):
            RuntimeSecretTradingAccountRepository.from_env(
                {
                    "TRADING_ACCOUNT_WALLET_ADDRESS": (
                        "0x1234567890abcdef1234567890abcdef1234abcd"
                    ),
                    "TRADING_ACCOUNT_SIGNATURE_TYPE": "2",
                    "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED": "encrypted",
                }
            )

    def test_factory_defaults_to_legacy_database(self) -> None:
        repository = build_trading_account_repository(
            database_url="postgresql://unused",
            environ={},
        )

        self.assertIsInstance(
            repository,
            SqlAlchemyTradingAccountRepository,
        )

    def test_factory_selects_single_secret_provider(self) -> None:
        with patch.object(
            RuntimeSecretTradingAccountRepository,
            "from_env",
            return_value=object(),
        ) as from_env:
            repository = build_trading_account_repository(
                database_url="postgresql://unused",
                environ={"TRADING_ACCOUNT_SOURCE": "single_secret"},
            )

        self.assertIs(repository, from_env.return_value)
        from_env.assert_called_once_with(
            {"TRADING_ACCOUNT_SOURCE": "single_secret"}
        )

    def test_factory_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(
            TradingAccountLoadError,
            "Unsupported",
        ):
            build_trading_account_repository(
                environ={"TRADING_ACCOUNT_SOURCE": "unknown"},
            )


if __name__ == "__main__":
    unittest.main()
