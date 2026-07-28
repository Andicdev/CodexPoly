from __future__ import annotations

import unittest

from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker as sqlalchemy_sessionmaker  # noqa: F401

from cbr_trading.live.account_repository import (
    SqlAlchemyRuntimeSecretTradingAccountRepository,
    SqlAlchemyTradingAccountRepository,
)
from cbr_trading.live.resolution_idempotency import (
    SqlAlchemyResolutionExecutionLedger,
)


class LiveDatabaseConnectionPoolingTests(unittest.TestCase):
    def test_legacy_account_reader_does_not_retain_idle_connection(
        self,
    ) -> None:
        repository = SqlAlchemyTradingAccountRepository(
            database_url="sqlite://"
        )

        repository._resolve_dependencies()

        self.assertIsInstance(repository._engine.pool, NullPool)

    def test_runtime_secret_account_reader_does_not_retain_connection(
        self,
    ) -> None:
        repository = SqlAlchemyRuntimeSecretTradingAccountRepository(
            database_url="sqlite://",
            configured_name="account",
            encrypted_private_key=b"test-ciphertext",
        )

        repository._resolve_dependencies()

        self.assertIsInstance(repository._engine.pool, NullPool)

    def test_per_profile_execution_ledger_does_not_retain_connection(
        self,
    ) -> None:
        ledger = SqlAlchemyResolutionExecutionLedger(
            database_url="sqlite://"
        )

        ledger._resolve_dependencies()

        self.assertIsInstance(ledger._engine.pool, NullPool)


if __name__ == "__main__":
    unittest.main()
