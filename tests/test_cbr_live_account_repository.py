from __future__ import annotations

import unittest

from cbr_trading.live.account_repository import (
    TradingAccountLoadError,
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


if __name__ == "__main__":
    unittest.main()
