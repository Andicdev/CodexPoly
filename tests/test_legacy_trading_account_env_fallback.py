from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "common"
    / "polymarket_utils.py"
)


def _load_legacy_polymarket_utils():
    clob_module = types.ModuleType("py_clob_client_v2")
    for name in (
        "ApiCreds",
        "AssetType",
        "BalanceAllowanceParams",
        "CancelOrderArgs",
        "ClobClient",
        "OpenOrderParams",
        "OrderArgs",
        "OrderType",
        "PartialCreateOrderOptions",
        "PostOrdersArgs",
        "Side",
    ):
        setattr(clob_module, name, type(name, (), {}))

    spec = importlib.util.spec_from_file_location(
        "_legacy_polymarket_utils_under_test",
        _MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load legacy Polymarket utilities")

    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "pandas": types.ModuleType("pandas"),
            "py_clob_client_v2": clob_module,
        },
    ):
        spec.loader.exec_module(module)
    return module


class LegacyTradingAccountEnvFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_legacy_polymarket_utils()

    def test_database_encrypted_key_keeps_priority(self) -> None:
        account = SimpleNamespace(
            name="legacy-account",
            pk_enc=b"database-encrypted-key",
        )
        with (
            patch.object(self.module.config, "PK", "local-plain-key"),
            patch.object(
                self.module,
                "read_runtime_secret",
                return_value="local-encrypted-key",
            ),
            patch.object(
                self.module,
                "_decrypt_pk",
                return_value="database-private-key",
            ) as decrypt,
        ):
            resolved = self.module._resolve_trading_account_pk(account)

        self.assertEqual(resolved, "database-private-key")
        decrypt.assert_called_once_with(b"database-encrypted-key")

    def test_database_account_may_keep_only_non_secret_metadata(
        self,
    ) -> None:
        account = SimpleNamespace(
            name="legacy-account",
            is_active=True,
            pk_enc=None,
            wallet_address="0x1234567890abcdef1234567890abcdef1234abcd",
            signature_type=2,
        )

        class _Result:
            def scalar_one_or_none(self):
                return account

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def execute(self, _statement):
                return _Result()

        with patch.object(self.module, "Session", _Session):
            loaded = self.module.get_trading_account_by_name(
                "legacy-account"
            )

        self.assertIs(loaded, account)

    def test_missing_database_keys_use_account_specific_env_keys(
        self,
    ) -> None:
        first_account = SimpleNamespace(
            name="kinderSman",
            pk_enc=None,
        )
        second_account = SimpleNamespace(
            name="sport-two",
            pk_enc=None,
        )
        encrypted_by_name = {
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_KINDERSMAN": (
                "encrypted-first"
            ),
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_SPORT_TWO": (
                "encrypted-second"
            ),
        }

        def read_secret(name, *, environ):
            self.assertIs(environ, self.module.os.environ)
            return encrypted_by_name.get(name)

        def decrypt(value):
            return {
                b"encrypted-first": "private-first",
                b"encrypted-second": "private-second",
            }[value]

        with (
            patch.dict(self.module.os.environ, {}, clear=True),
            patch.object(self.module.config, "PK", None),
            patch.object(
                self.module,
                "read_runtime_secret",
                side_effect=read_secret,
            ),
            patch.object(
                self.module,
                "_decrypt_pk",
                side_effect=decrypt,
            ),
        ):
            first = self.module._resolve_trading_account_pk(
                first_account
            )
            second = self.module._resolve_trading_account_pk(
                second_account
            )

        self.assertEqual(first, "private-first")
        self.assertEqual(second, "private-second")

    def test_single_account_encrypted_env_contract_is_preserved(
        self,
    ) -> None:
        account = SimpleNamespace(name="legacy-account", pk_enc=None)

        def read_secret(name, *, environ):
            self.assertIs(environ, self.module.os.environ)
            if name == "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED":
                return "single-encrypted-key"
            return None

        with (
            patch.dict(
                self.module.os.environ,
                {"TRADING_ACCOUNT_NAME": "LEGACY-ACCOUNT"},
                clear=True,
            ),
            patch.object(self.module.config, "PK", None),
            patch.object(
                self.module,
                "read_runtime_secret",
                side_effect=read_secret,
            ),
            patch.object(
                self.module,
                "_decrypt_pk",
                return_value="single-private-key",
            ) as decrypt,
        ):
            resolved = self.module._resolve_trading_account_pk(account)

        self.assertEqual(resolved, "single-private-key")
        decrypt.assert_called_once_with(b"single-encrypted-key")

    def test_missing_database_key_keeps_legacy_plain_env_fallback(
        self,
    ) -> None:
        account = SimpleNamespace(name="legacy-account", pk_enc=None)
        with (
            patch.dict(self.module.os.environ, {}, clear=True),
            patch.object(self.module.config, "PK", "local-plain-key"),
            patch.object(
                self.module,
                "read_runtime_secret",
                return_value=None,
            ),
            patch.object(self.module, "_decrypt_pk") as decrypt,
        ):
            resolved = self.module._resolve_trading_account_pk(account)

        self.assertEqual(resolved, "local-plain-key")
        decrypt.assert_not_called()

    def test_missing_database_and_env_key_fails_closed(self) -> None:
        account = SimpleNamespace(name="legacy-account", pk_enc=None)
        with (
            patch.dict(self.module.os.environ, {}, clear=True),
            patch.object(self.module.config, "PK", None),
            patch.object(
                self.module,
                "read_runtime_secret",
                return_value=None,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "no matching local env private key",
            ):
                self.module._resolve_trading_account_pk(account)


if __name__ == "__main__":
    unittest.main()
