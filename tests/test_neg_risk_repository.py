from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from neg_risk_trading.repository import (
    ObservationRepositoryError,
    RecordedStreamMessage,
    SqlAlchemyObservationRepository,
    StreamSessionStart,
)
from neg_risk_trading.stream import StreamStatus, StreamUpdate


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
SESSION_ID = UUID("12345678-1234-5678-1234-567812345678")
CONDITION_ID = "0x" + "a" * 64


class _FakeResult:
    def __init__(
        self,
        row: dict | None = None,
        *,
        rows: list[dict] | None = None,
    ):
        self._row = row
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def one(self) -> dict:
        if self._row is None:
            raise RuntimeError("row missing")
        return self._row

    def one_or_none(self) -> dict | None:
        return self._row

    def __iter__(self):
        if self._rows is not None:
            return iter(self._rows)
        return iter(() if self._row is None else (self._row,))


class _FakeSession:
    def __init__(self, *, schema_ready: bool = True):
        self.schema_ready = schema_ready
        self.executions: list[tuple[str, object]] = []
        self.message_ids: dict[tuple[str, int, int], int] = {}
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None

    def execute(
        self,
        sql: str,
        params: object = None,
    ) -> _FakeResult:
        self.executions.append((sql, params))
        if "AS sessions_table" in sql:
            return _FakeResult(
                {
                    "sessions_table": self.schema_ready,
                    "messages_table": True,
                    "observations_table": True,
                    "anomalies_table": True,
                    "sessions_columns": True,
                    "messages_columns": True,
                    "observations_columns": True,
                    "anomalies_columns": True,
                    "message_sequence_index": True,
                    "observation_route_index": True,
                    "messages_append_only": True,
                    "observations_append_only": True,
                    "anomalies_append_only": True,
                }
            )
        if "INSERT INTO neg_risk_stream_sessions" in sql:
            assert isinstance(params, dict)
            return _FakeResult(
                {"session_id": params["session_id"]}
            )
        if "INSERT INTO neg_risk_stream_messages" in sql:
            assert isinstance(params, dict)
            key = (
                str(params["session_id"]),
                int(params["connection_epoch"]),
                int(params["message_sequence"]),
            )
            if key in self.message_ids:
                return _FakeResult(None)
            row_id = len(self.message_ids) + 1
            self.message_ids[key] = row_id
            return _FakeResult({"id": row_id})
        if "SELECT id" in sql:
            assert isinstance(params, dict)
            key = (
                str(params["session_id"]),
                int(params["connection_epoch"]),
                int(params["message_sequence"]),
            )
            return _FakeResult({"id": self.message_ids[key]})
        return _FakeResult({})

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _ReplayFakeSession(_FakeSession):
    def execute(
        self,
        sql: str,
        params: object = None,
    ) -> _FakeResult:
        self.executions.append((sql, params))
        if (
            "FROM neg_risk_stream_sessions" in sql
            and "ORDER BY started_at" in sql
        ):
            return _FakeResult(
                {
                    "session_id": str(SESSION_ID),
                    "event_id": "481717",
                    "event_slug": (
                        "fed-decision-in-september-762"
                    ),
                    "started_at": NOW,
                    "ended_at": None,
                    "metadata": {
                        "quantities": ["200"],
                    },
                }
            )
        if "FROM neg_risk_stream_messages" in sql:
            return _FakeResult(
                rows=[
                    {
                        "connection_epoch": 1,
                        "message_sequence": 1,
                        "received_at": NOW,
                        "payload": {
                            "event_type": "book",
                        },
                    }
                ]
            )
        return super().execute(sql, params)


def _record() -> RecordedStreamMessage:
    update = StreamUpdate(
        event_type="book",
        affected_asset_ids=("10000",),
        timestamp_ms=2_000_000_000_000,
        received_at_ms=2_000_000_000_010,
        status=StreamStatus.READY,
        became_ready=True,
    )
    return RecordedStreamMessage(
        connection_epoch=1,
        message_sequence=1,
        received_at=NOW,
        payload={
            "event_type": "book",
            "asset_id": "10000",
        },
        updates=(update,),
        route_evaluation={
            "available_routes": [
                {
                    "available": True,
                    "route_direction": "MAKER_SELL",
                    "maker_condition_id": CONDITION_ID,
                    "maker_question": "Fed outcome?",
                    "maker_price": "0.57",
                    "quantity": "200",
                    "queue_ahead": "30000",
                    "hedge_legs": [],
                    "gross_collateral": "203.2",
                    "conservative_taker_fees": "2.9",
                    "base_profit": "0.3",
                    "base_edge_per_share": "0.0015",
                    "estimated_maker_rebate": "0.6",
                    "profit_with_rebate": "0.9",
                    "edge_with_rebate_per_share": "0.0045",
                    "reward": {
                        "top_of_book_candidate": True,
                    },
                }
            ],
            "unavailable_routes": [
                {
                    "available": False,
                    "route_direction": "MAKER_SELL",
                    "maker_condition_id": (
                        "0x" + "b" * 64
                    ),
                    "maker_question": "Other Fed outcome?",
                    "quantity": "200",
                    "reason_code": (
                        "hedge_depth_insufficient"
                    ),
                }
            ],
        },
    )


class MigrationTests(unittest.TestCase):
    def test_migration_is_shadow_only_and_append_only(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "neg_risk_trading"
            / "migrations"
            / "001_add_shadow_observation_tables.sql"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "CHECK (live_orders_enabled = false)",
            migration,
        )
        self.assertIn(
            "trg_neg_risk_stream_messages_append_only",
            migration,
        )
        self.assertIn(
            "trg_neg_risk_route_observations_append_only",
            migration,
        )
        self.assertNotIn("DROP TABLE", migration.upper())

    def test_bid_route_migration_is_append_only_and_directional(
        self,
    ) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "neg_risk_trading"
            / "migrations"
            / "003_add_bid_routes_and_stream_anomalies.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("route_direction text", migration)
        self.assertIn("'MAKER_BUY'", migration)
        self.assertIn("'MAKER_SELL'", migration)
        self.assertIn(
            "neg_risk_stream_anomalies",
            migration,
        )
        self.assertIn(
            "trg_neg_risk_stream_anomalies_append_only",
            migration,
        )
        self.assertNotIn("DROP TABLE", migration.upper())


class ObservationRepositoryTests(unittest.TestCase):
    def test_schema_readiness_fails_on_missing_contract(self) -> None:
        session = _FakeSession(schema_ready=False)
        repository = SqlAlchemyObservationRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        with self.assertRaisesRegex(
            ObservationRepositoryError,
            "sessions_table",
        ):
            repository.ensure_ready()

    def test_records_idempotent_message_and_routes(self) -> None:
        session = _FakeSession()
        repository = SqlAlchemyObservationRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        session_id = repository.start_session(
            StreamSessionStart(
                event_id="481717",
                event_slug="fed-decision-in-september-762",
                market_count=5,
                asset_count=10,
                started_at=NOW,
                metadata={"books_duration_ms": 100},
                session_id=SESSION_ID,
            )
        )

        inserted_first = repository.append_batch(
            session_id=session_id,
            messages=[_record()],
        )
        inserted_retry = repository.append_batch(
            session_id=session_id,
            messages=[_record()],
        )

        self.assertEqual(session_id, SESSION_ID)
        self.assertEqual(inserted_first, 1)
        self.assertEqual(inserted_retry, 0)
        route_calls = [
            params
            for sql, params in session.executions
            if "INSERT INTO neg_risk_route_observations" in sql
        ]
        self.assertEqual(len(route_calls), 2)
        self.assertEqual(len(route_calls[0]), 2)
        self.assertTrue(route_calls[0][0]["available"])
        self.assertIsNone(
            route_calls[0][0]["reason_code"]
        )
        self.assertFalse(route_calls[0][1]["available"])
        self.assertIsNone(
            route_calls[0][1]["maker_price"]
        )
        touch_calls = [
            params
            for sql, params in session.executions
            if "message_count = message_count" in sql
        ]
        self.assertEqual(len(touch_calls), 1)
        self.assertEqual(touch_calls[0]["message_count"], 1)
        self.assertTrue(touch_calls[0]["became_ready"])

    def test_database_errors_do_not_echo_exception_text(
        self,
    ) -> None:
        def broken_session() -> object:
            raise RuntimeError("sensitive failure detail")

        repository = SqlAlchemyObservationRepository(
            session_factory=broken_session,
            text_factory=lambda value: value,
        )

        with self.assertRaises(
            ObservationRepositoryError
        ) as raised:
            repository.ensure_ready()

        self.assertNotIn(
            "sensitive failure detail",
            str(raised.exception),
        )
        self.assertIn("RuntimeError", str(raised.exception))

    def test_reconnect_anomaly_keeps_only_safe_diagnostics(
        self,
    ) -> None:
        session = _FakeSession()
        repository = SqlAlchemyObservationRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        repository.mark_reconnecting(
            session_id=SESSION_ID,
            reason_code="price_change_best_bid_mismatch",
            connection_epoch=2,
            observed_at=NOW,
            diagnostics={
                "asset_id": "10000",
                "expected_bid": "0.40",
                "private_key": "must-not-persist",
            },
        )

        anomaly_calls = [
            params
            for sql, params in session.executions
            if "INSERT INTO neg_risk_stream_anomalies" in sql
        ]
        self.assertEqual(len(anomaly_calls), 1)
        self.assertIn('"asset_id":"10000"', anomaly_calls[0]["diagnostics"])
        self.assertNotIn("private_key", anomaly_calls[0]["diagnostics"])
        self.assertEqual(session.commits, 1)

    def test_loads_and_streams_public_replay_rows(self) -> None:
        session = _ReplayFakeSession()
        repository = SqlAlchemyObservationRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        replay_session = repository.load_replay_session()
        messages = list(
            repository.iter_replay_messages(
                session_id=replay_session.session_id,
            )
        )

        self.assertEqual(replay_session.session_id, SESSION_ID)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].connection_epoch, 1)
        self.assertEqual(messages[0].message_sequence, 1)
        self.assertEqual(
            messages[0].payload["event_type"],
            "book",
        )


if __name__ == "__main__":
    unittest.main()
