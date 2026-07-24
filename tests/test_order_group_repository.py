from __future__ import annotations

import unittest
from decimal import Decimal

from cbr_trading.domain import (
    ExecutionHandle,
    OrderSide,
    Outcome,
    PlacedOrder,
    RepriceOnTickChange,
)
from cbr_trading.execution import (
    OrderGroupStatus,
    SupervisionClaim,
    TickSizeChange,
    registration_from_handle,
)
from cbr_trading.live.order_group_repository import (
    OrderGroupRepositoryError,
    SqlAlchemyOrderGroupRepository,
    order_supervision_migration_sql,
)
from datetime import datetime, timezone


def _handle() -> ExecutionHandle:
    return ExecutionHandle(
        order_group_id="group-1",
        intent_id="signal-1/template-1",
        account_name="primary",
        condition_id="condition-1",
        outcome=Outcome.YES,
        asset_id="asset-yes",
        live_order_ids=("order-1",),
        signal_id="signal-1",
        template_id="template-1",
        strategy_id="strategy-1",
        side=OrderSide.BUY,
        desired_price=Decimal("0.999"),
        quantity=Decimal("25"),
    )


def _policy() -> RepriceOnTickChange:
    return RepriceOnTickChange(
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
        max_reprices=1,
    )


def _event() -> TickSizeChange:
    return TickSizeChange(
        event_id="tick-event-1",
        asset_id="asset-yes",
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
        observed_at=datetime(
            2026,
            7,
            24,
            13,
            30,
            tzinfo=timezone.utc,
        ),
    )


def _group_row(**overrides):
    row = {
        "order_group_id": "group-1",
        "intent_id": "signal-1/template-1",
        "signal_id": "signal-1",
        "template_id": "template-1",
        "strategy_id": "strategy-1",
        "account_name": "primary",
        "condition_id": "condition-1",
        "outcome": "YES",
        "asset_id": "asset-yes",
        "side": "BUY",
        "desired_price": Decimal("0.999"),
        "quantity": Decimal("25"),
        "notional": None,
        "policy_kind": "reprice_on_tick_change",
        "trigger_old_tick": Decimal("0.01"),
        "trigger_new_tick": Decimal("0.001"),
        "max_reprices": 1,
        "reprice_count": 0,
        "status": "ACTIVE",
        "revision": 0,
        "last_error": None,
        "metadata": {},
        "created_at": None,
        "updated_at": None,
        "initial_order_ids": ["order-1"],
        "live_order_ids": ["order-1"],
    }
    row.update(overrides)
    return row


class _Result:
    def __init__(
        self,
        *,
        one=None,
        one_or_none=None,
        all_rows=None,
        rowcount: int | None = None,
    ):
        self._one = one
        self._one_or_none = one_or_none
        self._all = list(all_rows or ())
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one(self):
        if self._one is None:
            raise AssertionError("No one() result configured")
        return self._one

    def one_or_none(self):
        return self._one_or_none

    def all(self):
        return self._all


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


class OrderGroupStateTests(unittest.TestCase):
    def test_repricing_registration_captures_exact_order_ownership(self) -> None:
        registration = registration_from_handle(
            _handle(),
            policy=_policy(),
        )

        self.assertEqual(registration.order_group_id, "group-1")
        self.assertEqual(registration.initial_order_ids, ("order-1",))
        self.assertEqual(
            registration.policy_kind,
            "reprice_on_tick_change",
        )
        self.assertEqual(registration.desired_price, Decimal("0.999"))

    def test_repricing_requires_replacement_order_parameters(self) -> None:
        incomplete = ExecutionHandle(
            order_group_id="group-1",
            intent_id="intent-1",
            account_name="primary",
            condition_id="condition-1",
            outcome=Outcome.YES,
            asset_id="asset-yes",
            live_order_ids=("order-1",),
        )

        with self.assertRaisesRegex(ValueError, "side, price, and size"):
            registration_from_handle(
                incomplete,
                policy=_policy(),
            )


class AdditiveMigrationTests(unittest.TestCase):
    def test_migration_only_creates_new_objects(self) -> None:
        sql = order_supervision_migration_sql().upper()

        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 3)
        self.assertNotIn("ALTER TABLE", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("DROP COLUMN", sql)
        self.assertNotIn("NEWS_TRADE_CONFIRMATIONS", sql)
        self.assertNotIn("STRATEGY_INSTANCES", sql)
        self.assertIn("RESOLUTION_ORDER_GROUPS", sql)
        self.assertIn("RESOLUTION_ORDER_GROUP_ORDERS", sql)
        self.assertIn("RESOLUTION_SUPERVISION_EVENTS", sql)

    def test_migrate_executes_additive_script_in_one_transaction(self) -> None:
        session = _Session([_Result()])
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        repository.migrate()

        self.assertEqual(session.commits, 1)
        self.assertEqual(len(session.calls), 1)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS resolution_order_groups",
            session.calls[0][0],
        )

    def test_ready_check_requires_all_three_new_tables(self) -> None:
        session = _Session(
            [
                _Result(
                    one={
                        "groups_table": True,
                        "groups_columns": True,
                        "orders_table": True,
                        "orders_columns": True,
                        "events_table": True,
                        "events_columns": True,
                    }
                )
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        repository.ensure_ready()

        self.assertEqual(len(session.calls), 1)


class SqlAlchemyOrderGroupRepositoryTests(unittest.TestCase):
    def test_register_inserts_group_and_owned_orders_atomically(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"order_group_id": "group-1"}),
                _Result(rowcount=1),
                _Result(one=_group_row()),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        record = repository.register(_handle(), policy=_policy())

        self.assertEqual(record.status, OrderGroupStatus.ACTIVE)
        self.assertEqual(record.live_order_ids, ("order-1",))
        self.assertEqual(session.commits, 1)
        self.assertEqual(len(session.calls), 3)
        self.assertIn(
            "INSERT INTO resolution_order_group_orders",
            session.calls[1][0],
        )

    def test_identical_registration_is_idempotent(self) -> None:
        session = _Session(
            [
                _Result(one_or_none=None),
                _Result(one=_group_row()),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        record = repository.register(_handle(), policy=_policy())

        self.assertEqual(record.registration.order_group_id, "group-1")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.commits, 1)

    def test_conflicting_registration_rolls_back(self) -> None:
        session = _Session(
            [
                _Result(one_or_none=None),
                _Result(one=_group_row(account_name="another-account")),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(
            OrderGroupRepositoryError,
            "conflicts",
        ):
            repository.register(_handle(), policy=_policy())

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_load_active_is_scoped_to_one_asset(self) -> None:
        session = _Session([_Result(all_rows=[_group_row()])])
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        records = repository.load_active_for_asset("asset-yes")

        self.assertEqual(len(records), 1)
        self.assertEqual(
            session.calls[0][1],
            {"asset_id": "asset-yes"},
        )
        self.assertIn("groups.status = 'ACTIVE'", session.calls[0][0])

    def test_tick_event_claim_is_atomic_and_revisioned(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"status": "RECEIVED"}),
                _Result(one_or_none={"revision": 1}),
                _Result(rowcount=1),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claim = repository.claim_tick_size_change(
            order_group_id="group-1",
            event=_event(),
        )

        self.assertEqual(
            claim,
            SupervisionClaim(
                event_id="tick-event-1",
                order_group_id="group-1",
                acquired=True,
                revision=1,
            ),
        )
        self.assertEqual(session.commits, 1)
        self.assertIn("status = 'REPRICING'", session.calls[1][0])

    def test_duplicate_tick_event_is_not_claimed_twice(self) -> None:
        session = _Session(
            [
                _Result(one_or_none=None),
                _Result(one={"status": "CLAIMED"}),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claim = repository.claim_tick_size_change(
            order_group_id="group-1",
            event=_event(),
        )

        self.assertFalse(claim.acquired)
        self.assertEqual(claim.reason, "duplicate_event:claimed")
        self.assertEqual(session.rollbacks, 1)

    def test_unclaimable_group_records_ignored_event(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"status": "RECEIVED"}),
                _Result(one_or_none=None),
                _Result(rowcount=1),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        claim = repository.claim_tick_size_change(
            order_group_id="group-1",
            event=_event(),
        )

        self.assertFalse(claim.acquired)
        self.assertEqual(claim.reason, "order_group_not_claimable")
        self.assertEqual(session.commits, 1)

    def test_fail_claim_updates_group_and_event_together(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"failed_generation": 1}),
                _Result(rowcount=1),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        claim = SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )

        repository.fail_claim(claim, error="replacement failed")

        self.assertEqual(session.commits, 1)
        self.assertEqual(
            session.calls[0][1]["error"],
            "replacement failed",
        )

    def test_complete_reprice_closes_exact_orders_and_tracks_replacement(
        self,
    ) -> None:
        replacement = PlacedOrder(
            order_id="order-2",
            asset_id="asset-yes",
            effective_price=Decimal("0.999"),
            quantity=Decimal("25"),
        )
        session = _Session(
            [
                _Result(
                    one_or_none={
                        "reprice_count": 1,
                        "status": "COMPLETED",
                        "revision": 2,
                    }
                ),
                _Result(all_rows=[{"order_id": "order-1"}]),
                _Result(rowcount=1),
                _Result(rowcount=1),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        claim = SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )

        repository.complete_reprice(
            claim,
            cancelled_order_ids=("order-1",),
            replacement_orders=(replacement,),
        )

        self.assertEqual(session.commits, 1)
        self.assertEqual(session.calls[1][1]["order_ids"], ["order-1"])
        self.assertEqual(session.calls[1][1]["status"], "REPLACED")
        self.assertEqual(session.calls[2][1]["order_id"], "order-2")
        self.assertEqual(session.calls[2][1]["status"], "LIVE")
        self.assertEqual(session.calls[2][1]["generation"], 1)

    def test_complete_reprice_rejects_non_owned_order_transition(
        self,
    ) -> None:
        session = _Session(
            [
                _Result(
                    one_or_none={
                        "reprice_count": 1,
                        "status": "COMPLETED",
                        "revision": 2,
                    }
                ),
                _Result(all_rows=[]),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        claim = SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )

        with self.assertRaisesRegex(
            OrderGroupRepositoryError,
            "ownership no longer matches",
        ):
            repository.complete_reprice(
                claim,
                cancelled_order_ids=("order-1",),
                replacement_orders=(
                    PlacedOrder(
                        order_id="order-2",
                        asset_id="asset-yes",
                        effective_price=Decimal("0.999"),
                        quantity=Decimal("25"),
                    ),
                ),
            )

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_fail_claim_records_known_external_side_effects(self) -> None:
        session = _Session(
            [
                _Result(one_or_none={"failed_generation": 1}),
                _Result(all_rows=[{"order_id": "order-1"}]),
                _Result(rowcount=1),
                _Result(rowcount=1),
            ]
        )
        repository = SqlAlchemyOrderGroupRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        claim = SupervisionClaim(
            event_id="tick-event-1",
            order_group_id="group-1",
            acquired=True,
            revision=1,
        )

        repository.fail_claim(
            claim,
            error="state persistence failed after placement",
            cancelled_order_ids=("order-1",),
            replacement_orders=(
                PlacedOrder(
                    order_id="order-2",
                    asset_id="asset-yes",
                    effective_price=Decimal("0.999"),
                    quantity=Decimal("25"),
                ),
            ),
        )

        self.assertEqual(session.commits, 1)
        self.assertEqual(session.calls[1][1]["status"], "CANCELLED")
        self.assertEqual(session.calls[2][1]["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
