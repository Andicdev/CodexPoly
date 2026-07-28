from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from cbr_trading.db_runtime import SharedSqlAlchemyRuntime


class SharedSqlAlchemyRuntimeTests(unittest.TestCase):
    @patch("sqlalchemy.orm.sessionmaker")
    @patch("sqlalchemy.create_engine")
    def test_builds_one_bounded_postgres_pool(
        self,
        create_engine: Mock,
        sessionmaker: Mock,
    ) -> None:
        engine = Mock()
        factory = Mock()
        create_engine.return_value = engine
        sessionmaker.return_value = factory

        runtime = SharedSqlAlchemyRuntime(
            database_url="postgres://db.example/codexpoly",
            application_name="codexpoly-resolution",
            pool_size=3,
            max_overflow=2,
            pool_timeout=4,
        )

        create_engine.assert_called_once_with(
            "postgresql://db.example/codexpoly",
            pool_size=3,
            max_overflow=2,
            pool_timeout=4.0,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_reset_on_return="rollback",
            hide_parameters=True,
            connect_args={
                "application_name": "codexpoly-resolution",
            },
        )
        sessionmaker.assert_called_once_with(
            bind=engine,
            expire_on_commit=False,
        )
        self.assertIs(runtime.session_factory, factory)

        runtime.close()
        runtime.close()

        engine.dispose.assert_called_once_with()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            _ = runtime.session_factory

    def test_rejects_invalid_pool_configuration(self) -> None:
        invalid_cases = (
            {"pool_size": 0, "max_overflow": 0},
            {"pool_size": 1, "max_overflow": -1},
        )
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    SharedSqlAlchemyRuntime(
                        database_url="postgresql://db/codexpoly",
                        application_name="codexpoly-test",
                        **values,
                    )

        with self.assertRaisesRegex(ValueError, "application_name"):
            SharedSqlAlchemyRuntime(
                database_url="postgresql://db/codexpoly",
                application_name="invalid application name",
                pool_size=1,
                max_overflow=0,
            )


if __name__ == "__main__":
    unittest.main()
