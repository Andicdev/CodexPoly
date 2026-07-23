from __future__ import annotations

import unittest
from decimal import Decimal

from cbr_trading.rule_repository import (
    CBR_CHANGE_METRIC,
    CBR_EXECUTION_PATH,
    CBR_TICKER,
    RuleLoadError,
    SqlAlchemyRuleRepository,
    normalize_rule_rows,
)
from cbr_trading.settings import CbrSettings


class FakeResult:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple[str, dict | None]] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        params: dict | None = None,
    ) -> FakeResult:
        self.calls.append((statement, params))
        return FakeResult(self.rows)


def _row() -> dict:
    return {
        "id": 17,
        "rule_key": "cbr_cut",
        "params": {
            "metric_key": CBR_CHANGE_METRIC,
            "execution_path": CBR_EXECUTION_PATH,
            "threshold": -25,
            "cmp": "<=",
        },
        "tg_chat_id": "-100123",
        "account_name": "main",
        "condition_id": "condition-17",
        "question": "Will the rate be cut?",
        "order_qty": Decimal("100.5"),
        "order_price": Decimal("0.51"),
    }


class RuleRepositoryTests(unittest.TestCase):
    def test_forces_read_only_then_runs_legacy_cbr_filter(self) -> None:
        session = FakeSession([_row()])
        repository = SqlAlchemyRuleRepository(
            session_factory=lambda: session,
            text_factory=lambda statement: statement,
        )

        rules = repository.load_active_cbr_rules()

        self.assertEqual(len(session.calls), 2)
        self.assertEqual(
            session.calls[0][0],
            "SET TRANSACTION READ ONLY",
        )
        select_sql, params = session.calls[1]
        self.assertTrue(select_sql.lstrip().startswith("SELECT"))
        self.assertNotIn("INSERT", select_sql.upper())
        self.assertNotIn("UPDATE", select_sql.upper())
        self.assertNotIn("DELETE", select_sql.upper())
        self.assertIn("ORDER BY priority ASC, id ASC", select_sql)
        self.assertEqual(
            params,
            {
                "status": "active",
                "ticker": CBR_TICKER,
                "metric_key": CBR_CHANGE_METRIC,
                "execution_path": CBR_EXECUTION_PATH,
            },
        )
        self.assertEqual(rules[0]["order_qty"], 100.5)
        self.assertEqual(rules[0]["order_price"], 0.51)

    def test_invalid_optional_values_are_left_for_pipeline_validation(
        self,
    ) -> None:
        row = _row()
        row["params"] = "not-json"
        row["order_qty"] = "bad"
        row["order_price"] = None

        rule = normalize_rule_rows([row])[0]

        self.assertEqual(rule["params"], {})
        self.assertIsNone(rule["order_qty"])
        self.assertIsNone(rule["order_price"])

    def test_invalid_rule_id_fails_closed(self) -> None:
        row = _row()
        row["id"] = None
        with self.assertRaisesRegex(RuleLoadError, "invalid id"):
            normalize_rule_rows([row])

    def test_database_error_is_sanitized(self) -> None:
        class FailingSession(FakeSession):
            def execute(
                self,
                statement: str,
                params: dict | None = None,
            ) -> FakeResult:
                raise RuntimeError("postgres://user:secret@example")

        repository = SqlAlchemyRuleRepository(
            session_factory=lambda: FailingSession([]),
            text_factory=lambda statement: statement,
        )

        with self.assertRaises(RuleLoadError) as raised:
            repository.load_active_cbr_rules()

        self.assertIn("RuntimeError", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))


class RuleRepositorySettingsTests(unittest.TestCase):
    def test_database_rules_are_opt_in(self) -> None:
        settings = CbrSettings.from_env({})
        self.assertFalse(settings.rules_db_enabled)
        self.assertIsNone(settings.rules_database_url)

    def test_reads_database_rule_settings(self) -> None:
        settings = CbrSettings.from_env(
            {
                "CBR_RULES_DB_ENABLED": "1",
                "CBR_DATABASE_URL": "postgresql://user:secret@db/app",
            }
        )
        self.assertTrue(settings.rules_db_enabled)
        self.assertEqual(
            settings.rules_database_url,
            "postgresql://user:secret@db/app",
        )
        self.assertNotIn("secret", repr(settings))

    def test_enabled_database_rules_require_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "CBR_DATABASE_URL"):
            CbrSettings.from_env(
                {"CBR_RULES_DB_ENABLED": "1"}
            )


if __name__ == "__main__":
    unittest.main()
