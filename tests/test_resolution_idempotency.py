from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from cbr_trading.domain import (
    OrderSide,
    OrderTemplate,
    Outcome,
)
from cbr_trading.execution import PreparationContext
from cbr_trading.live.resolution_idempotency import (
    ResolutionExecutionLedgerError,
    SqlAlchemyResolutionExecutionLedger,
    make_resolution_idempotency_key,
)


def _template() -> OrderTemplate:
    return OrderTemplate(
        template_id="fixed-outcome-rule:103:YES",
        strategy_id="fixed_outcome",
        account_name="KinderSman",
        condition_id="0x" + ("7" * 64),
        outcome=Outcome.YES,
        side=OrderSide.BUY,
        desired_price=Decimal("0.9"),
        quantity=Decimal("5"),
        metadata={"rule_id": 103, "rule_key": "opus_yes"},
    )


def _context() -> PreparationContext:
    return PreparationContext(
        scope_id="manual-live-test:run-1:rule:103",
        source="anthropic_official",
        source_reference="manual://resolution-live-test/run-1",
    )


class _Result:
    def __init__(self, *, one=None, one_or_none=None):
        self._one = one
        self._one_or_none = one_or_none

    def mappings(self):
        return self

    def one(self):
        if self._one is None:
            raise AssertionError("No one() result configured")
        return self._one

    def one_or_none(self):
        return self._one_or_none


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return self.results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ResolutionExecutionLedgerTests(unittest.TestCase):
    def test_key_is_stable_and_scoped_to_template(self) -> None:
        first = make_resolution_idempotency_key(
            scope_id="scope-1",
            template_id="template-1",
        )
        repeated = make_resolution_idempotency_key(
            scope_id="scope-1",
            template_id="template-1",
        )
        other = make_resolution_idempotency_key(
            scope_id="scope-1",
            template_id="template-2",
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("resolution:v1:"))

    def test_ready_check_requires_table_columns_and_indexes(self) -> None:
        session = _Session(
            [
                _Result(
                    one={
                        "claims_table": True,
                        "claims_columns": True,
                        "id_generated": True,
                        "key_index": True,
                        "scope_template_index": True,
                    }
                )
            ]
        )
        ledger = SqlAlchemyResolutionExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        ledger.ensure_ready()

        self.assertEqual(len(session.calls), 1)

    def test_reserves_all_templates_in_one_commit(self) -> None:
        session = _Session(
            [_Result(one_or_none={"id": 41})]
        )
        ledger = SqlAlchemyResolutionExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claims = ledger.reserve_many(
            context=_context(),
            templates=(_template(),),
            effective_prices={
                "fixed-outcome-rule:103:YES": Decimal("0.9")
            },
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_id, 41)
        self.assertEqual(session.commits, 1)
        params = session.calls[0][1]
        self.assertEqual(params["scope_id"], _context().scope_id)
        self.assertEqual(params["outcome"], "YES")
        self.assertEqual(params["quantity"], Decimal("5"))

    def test_duplicate_rolls_back_before_polling(self) -> None:
        session = _Session(
            [
                _Result(one_or_none=None),
                _Result(
                    one_or_none={"id": 41, "status": "EXECUTED"}
                ),
            ]
        )
        ledger = SqlAlchemyResolutionExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(
            ResolutionExecutionLedgerError,
            "already claimed",
        ):
            ledger.reserve_many(
                context=_context(),
                templates=(_template(),),
                effective_prices={
                    "fixed-outcome-rule:103:YES": Decimal("0.9")
                },
            )

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_completion_and_cleanup_update_exact_claim(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"id": 41}),
                _Result(one_or_none={"id": 41}),
            ]
        )
        ledger = SqlAlchemyResolutionExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        ledger.complete(
            41,
            status="EXECUTED",
            result={"order_ids": ["order-1"]},
        )
        ledger.record_cleanup(
            41,
            cleanup={"confirmed_terminal": True},
        )

        self.assertEqual(session.commits, 2)
        self.assertEqual(session.calls[0][1]["claim_id"], 41)
        self.assertEqual(session.calls[1][1]["claim_id"], 41)
        self.assertIn("smoke_cleanup", session.calls[1][0])

    def test_migration_is_additive_only(self) -> None:
        sql = (
            Path(__file__).resolve().parents[1]
            / "cbr_trading"
            / "migrations"
            / "003_add_resolution_execution_claims.sql"
        ).read_text(encoding="utf-8").upper()

        self.assertIn(
            "CREATE TABLE IF NOT EXISTS "
            "RESOLUTION_EXECUTION_CLAIMS",
            sql,
        )
        self.assertNotIn("ALTER TABLE", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("DROP COLUMN", sql)


if __name__ == "__main__":
    unittest.main()
