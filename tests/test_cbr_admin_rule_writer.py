from __future__ import annotations

import unittest

from cbr_trading.admin.rule_writer import (
    RuleWriteError,
    SqlAlchemyRuleWriter,
)
from cbr_trading.admin.templates import RuleDraft


class FakeResult:
    def __init__(
        self,
        *,
        values: list[int] | None = None,
        scalar: int | None = None,
    ):
        self.values = values or []
        self.scalar = scalar

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[int]:
        return self.values

    def scalar_one(self) -> int:
        if self.scalar is None:
            raise AssertionError("scalar_one was not configured")
        return self.scalar


class FakeTransaction:
    def __init__(self, session: "FakeSession"):
        self.session = session

    def __enter__(self) -> "FakeTransaction":
        self.session.transaction_entered = True
        return self

    def __exit__(self, *args: object) -> None:
        self.session.transaction_exited = True
        return None


class FakeSession:
    def __init__(
        self,
        existing: dict[str, list[int]] | None = None,
    ):
        self.existing = existing or {}
        self.calls: list[tuple[str, dict | None]] = []
        self.next_id = 100
        self.transaction_entered = False
        self.transaction_exited = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(
        self,
        statement: str,
        params: dict | None = None,
    ) -> FakeResult:
        self.calls.append((statement, params))
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT PG_ADVISORY"):
            return FakeResult(scalar=1)
        if normalized.startswith("SELECT ID"):
            key = str((params or {}).get("rule_key") or "")
            return FakeResult(values=self.existing.get(key, []))
        if normalized.startswith("UPDATE"):
            return FakeResult(scalar=int((params or {})["id"]))
        if normalized.startswith("INSERT"):
            self.next_id += 1
            return FakeResult(scalar=self.next_id)
        raise AssertionError(f"Unexpected SQL: {statement}")


def _draft(rule_key: str, marker: str) -> RuleDraft:
    return RuleDraft(
        type="cbr_key_rate",
        ticker="CBR",
        rule_key=rule_key,
        status="active",
        priority=300,
        tg_chat_id=None,
        account_name="main",
        condition_id="0x" + marker * 64,
        question=f"Question {marker}",
        order_qty=10,
        order_price=0.99,
        params={
            "metric_key": "cbr_key_rate_change_bp",
            "cmp": "<",
            "threshold": 0,
        },
    )


class RuleWriterTests(unittest.TestCase):
    def test_updates_existing_and_creates_missing_in_one_transaction(
        self,
    ) -> None:
        session = FakeSession({"cbr_decrease_fast": [7]})
        writer = SqlAlchemyRuleWriter(
            session_factory=lambda: session,
            text_factory=lambda statement: statement,
        )

        results = writer.apply_rules(
            [
                _draft("cbr_decrease_fast", "a"),
                _draft("cbr_increase_fast", "b"),
            ]
        )

        self.assertEqual(
            [result.action for result in results],
            ["updated", "created"],
        )
        self.assertEqual([result.rule_id for result in results], [7, 101])
        self.assertTrue(session.transaction_entered)
        self.assertTrue(session.transaction_exited)
        self.assertTrue(
            session.calls[0][0]
            .lstrip()
            .upper()
            .startswith("SELECT PG_ADVISORY")
        )

    def test_duplicate_identity_fails_instead_of_guessing(self) -> None:
        session = FakeSession({"cbr_decrease_fast": [7, 8]})
        writer = SqlAlchemyRuleWriter(
            session_factory=lambda: session,
            text_factory=lambda statement: statement,
        )

        with self.assertRaisesRegex(
            RuleWriteError,
            "Multiple monitored_news rows",
        ):
            writer.apply_rules([_draft("cbr_decrease_fast", "a")])

    def test_write_url_is_required_and_hidden(self) -> None:
        writer = SqlAlchemyRuleWriter()
        with self.assertRaisesRegex(
            RuleWriteError,
            "CBR_ADMIN_DATABASE_URL",
        ):
            writer.apply_rules([_draft("cbr_decrease_fast", "a")])

        configured = SqlAlchemyRuleWriter(
            database_url="postgresql://user:secret@db/app"
        )
        self.assertNotIn("secret", repr(configured))


if __name__ == "__main__":
    unittest.main()
