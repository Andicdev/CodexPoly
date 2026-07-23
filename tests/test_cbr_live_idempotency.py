from __future__ import annotations

import unittest

from cbr_trading.live.idempotency import (
    ExecutionClaim,
    SqlAlchemyExecutionLedger,
    make_idempotency_key,
)
from cbr_trading.pipeline import OrderIntent


def _intent(*, action: str = "YES") -> OrderIntent:
    return OrderIntent(
        rule_id=98,
        rule_key="cbr_decrease_fast",
        account_name="kinderSman",
        condition_id="0x" + ("a" * 64),
        action=action,
        quantity=100,
        limit_price=0.20,
        ready=True,
        reason="ready",
    )


class _Result:
    def __init__(
        self,
        *,
        one: dict | None = None,
        one_or_none: dict | None = None,
        rowcount: int | None = None,
    ):
        self._one = one
        self._one_or_none = one_or_none
        self.rowcount = rowcount

    def mappings(self) -> "_Result":
        return self

    def one(self) -> dict:
        if self._one is None:
            raise AssertionError("No one() result configured")
        return self._one

    def one_or_none(self) -> dict | None:
        return self._one_or_none


class _Session:
    def __init__(self, results: list[_Result]):
        self.results = list(results)
        self.calls: list[tuple[str, dict | None]] = []
        self.commits = 0

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        params: dict | None = None,
    ) -> _Result:
        self.calls.append((statement, params))
        return self.results.pop(0)

    def commit(self) -> None:
        self.commits += 1


class ExecutionLedgerTests(unittest.TestCase):
    def test_ready_check_requires_schema_and_unique_key(self) -> None:
        session = _Session(
            [
                _Result(
                    one={
                        "table_exists": True,
                        "columns_ready": True,
                        "key_unique": True,
                        "id_generated": True,
                    }
                )
            ]
        )
        ledger = SqlAlchemyExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        ledger.ensure_ready()

        self.assertEqual(len(session.calls), 1)

    def test_key_is_stable_and_scoped_to_action(self) -> None:
        first = make_idempotency_key(
            release_url="https://cbr.ru/release",
            intent=_intent(action="YES"),
        )
        repeated = make_idempotency_key(
            release_url="https://cbr.ru/release",
            intent=_intent(action="YES"),
        )
        opposite = make_idempotency_key(
            release_url="https://cbr.ru/release",
            intent=_intent(action="NO"),
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, opposite)
        self.assertTrue(first.startswith("cbr_auto:v1:"))

    def test_claim_inserts_once_and_returns_database_id(self) -> None:
        session = _Session(
            [_Result(one_or_none={"id": 41, "status": "EXECUTING"})]
        )
        ledger = SqlAlchemyExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claim = ledger.claim(
            release_url="https://cbr.ru/release",
            intent=_intent(),
        )

        self.assertEqual(
            claim,
            ExecutionClaim(
                acquired=True,
                idempotency_key=claim.idempotency_key,
                claim_id=41,
            ),
        )
        self.assertEqual(session.commits, 1)
        params = session.calls[0][1] or {}
        self.assertEqual(params["action"], "YES")
        self.assertEqual(params["sub_id"], 98)

    def test_duplicate_claim_returns_existing_order(self) -> None:
        session = _Session(
            [
                _Result(one_or_none=None),
                _Result(
                    one={
                        "id": 41,
                        "status": "EXECUTED",
                        "result": {"order_id": "order-123"},
                        "error": None,
                    }
                ),
            ]
        )
        ledger = SqlAlchemyExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claim = ledger.claim(
            release_url="https://cbr.ru/release",
            intent=_intent(),
        )

        self.assertFalse(claim.acquired)
        self.assertEqual(claim.existing_status, "EXECUTED")
        self.assertEqual(claim.existing_order_id, "order-123")
        self.assertEqual(session.commits, 1)

    def test_complete_updates_only_executing_claim(self) -> None:
        session = _Session([_Result(rowcount=1)])
        ledger = SqlAlchemyExecutionLedger(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        ledger.complete(
            claim_id=41,
            status="EXECUTED",
            result={"order_id": "order-123"},
        )

        self.assertEqual(session.commits, 1)
        params = session.calls[0][1] or {}
        self.assertEqual(params["claim_id"], 41)
        self.assertEqual(params["status"], "EXECUTED")


if __name__ == "__main__":
    unittest.main()
