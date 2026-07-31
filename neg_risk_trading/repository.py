from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from neg_risk_trading.domain import RouteDirection
from neg_risk_trading.stream import StreamUpdate


_MIGRATION_PATH = (
    Path(__file__).resolve().parent
    / "migrations"
    / "001_add_shadow_observation_tables.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('neg_risk_stream_sessions') IS NOT NULL
        AS sessions_table,
    to_regclass('neg_risk_stream_messages') IS NOT NULL
        AS messages_table,
    to_regclass('neg_risk_route_observations') IS NOT NULL
        AS observations_table,
    (
        SELECT count(*) = 17
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_sessions'
    ) AS sessions_columns,
    (
        SELECT count(*) = 12
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_messages'
    ) AS messages_columns,
    (
        SELECT count(*) = 23
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_route_observations'
    ) AS observations_columns,
    to_regclass('neg_risk_stream_anomalies') IS NOT NULL
        AS anomalies_table,
    (
        SELECT count(*) = 6
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_anomalies'
    ) AS anomalies_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_neg_risk_stream_messages_sequence'
        )
          AND indisunique
    ) AS message_sequence_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_neg_risk_route_observations_route'
        )
          AND indisunique
    ) AS observation_route_index,
    EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = to_regclass(
            'neg_risk_stream_messages'
        )
          AND tgname =
              'trg_neg_risk_stream_messages_append_only'
          AND NOT tgisinternal
    ) AS messages_append_only,
    EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = to_regclass(
            'neg_risk_route_observations'
        )
          AND tgname =
              'trg_neg_risk_route_observations_append_only'
          AND NOT tgisinternal
    ) AS observations_append_only,
    EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = to_regclass(
            'neg_risk_stream_anomalies'
        )
          AND tgname =
              'trg_neg_risk_stream_anomalies_append_only'
          AND NOT tgisinternal
    ) AS anomalies_append_only
""".strip()

_INSERT_SESSION_SQL = """
INSERT INTO neg_risk_stream_sessions (
    session_id,
    event_id,
    event_slug,
    mode,
    status,
    market_count,
    asset_count,
    started_at,
    live_orders_enabled,
    metadata
)
VALUES (
    :session_id,
    :event_id,
    :event_slug,
    'SHADOW',
    'STARTING',
    :market_count,
    :asset_count,
    :started_at,
    false,
    CAST(:metadata AS jsonb)
)
RETURNING session_id
""".strip()

_INSERT_MESSAGE_SQL = """
INSERT INTO neg_risk_stream_messages (
    session_id,
    connection_epoch,
    message_sequence,
    received_at,
    server_timestamp_min_ms,
    server_timestamp_max_ms,
    event_types,
    affected_asset_ids,
    payload,
    payload_bytes,
    event_count
)
VALUES (
    :session_id,
    :connection_epoch,
    :message_sequence,
    :received_at,
    :server_timestamp_min_ms,
    :server_timestamp_max_ms,
    CAST(:event_types AS jsonb),
    CAST(:affected_asset_ids AS jsonb),
    CAST(:payload AS jsonb),
    :payload_bytes,
    :event_count
)
ON CONFLICT (
    session_id,
    connection_epoch,
    message_sequence
) DO NOTHING
RETURNING id
""".strip()

_SELECT_MESSAGE_SQL = """
SELECT id
FROM neg_risk_stream_messages
WHERE session_id = :session_id
  AND connection_epoch = :connection_epoch
  AND message_sequence = :message_sequence
""".strip()

_INSERT_ROUTE_SQL = """
INSERT INTO neg_risk_route_observations (
    session_id,
    stream_message_id,
    connection_epoch,
    observed_at,
    trigger_event_type,
    route_direction,
    maker_condition_id,
    maker_question,
    quantity,
    available,
    reason_code,
    maker_price,
    queue_ahead,
    gross_collateral,
    conservative_taker_fees,
    base_profit,
    base_edge_per_share,
    estimated_maker_rebate,
    profit_with_rebate,
    edge_with_rebate_per_share,
    reward_top_of_book_candidate,
    hedge_legs
)
VALUES (
    :session_id,
    :stream_message_id,
    :connection_epoch,
    :observed_at,
    :trigger_event_type,
    :route_direction,
    :maker_condition_id,
    :maker_question,
    :quantity,
    :available,
    :reason_code,
    :maker_price,
    :queue_ahead,
    :gross_collateral,
    :conservative_taker_fees,
    :base_profit,
    :base_edge_per_share,
    :estimated_maker_rebate,
    :profit_with_rebate,
    :edge_with_rebate_per_share,
    :reward_top_of_book_candidate,
    CAST(:hedge_legs AS jsonb)
)
ON CONFLICT (
    stream_message_id,
    route_direction,
    maker_condition_id,
    quantity
) DO NOTHING
""".strip()

_TOUCH_SESSION_SQL = """
UPDATE neg_risk_stream_sessions
SET
    status = CASE
        WHEN :became_ready THEN 'READY'
        ELSE status
    END,
    ready_at = CASE
        WHEN :became_ready
        THEN COALESCE(ready_at, :last_message_at)
        ELSE ready_at
    END,
    last_message_at = CASE
        WHEN last_message_at IS NULL
          OR last_message_at < :last_message_at
        THEN :last_message_at
        ELSE last_message_at
    END,
    message_count = message_count + :message_count,
    update_count = update_count + :update_count
WHERE session_id = :session_id
""".strip()

_RECONNECT_SESSION_SQL = """
UPDATE neg_risk_stream_sessions
SET
    status = 'RECONNECTING',
    reconnect_count = reconnect_count + 1,
    reason_code = :reason_code
WHERE session_id = :session_id
  AND ended_at IS NULL
""".strip()

_INSERT_ANOMALY_SQL = """
INSERT INTO neg_risk_stream_anomalies (
    session_id,
    connection_epoch,
    observed_at,
    reason_code,
    diagnostics
)
VALUES (
    :session_id,
    :connection_epoch,
    :observed_at,
    :reason_code,
    CAST(:diagnostics AS jsonb)
)
""".strip()

_FINISH_SESSION_SQL = """
UPDATE neg_risk_stream_sessions
SET
    status = :status,
    ended_at = :ended_at,
    reason_code = :reason_code
WHERE session_id = :session_id
  AND ended_at IS NULL
""".strip()

_SELECT_LATEST_REPLAY_SESSION_SQL = """
SELECT
    session_id,
    event_id,
    event_slug,
    started_at,
    ended_at,
    metadata
FROM neg_risk_stream_sessions
WHERE mode = 'SHADOW'
  AND NOT live_orders_enabled
ORDER BY started_at DESC
LIMIT 1
""".strip()

_SELECT_REPLAY_SESSION_SQL = """
SELECT
    session_id,
    event_id,
    event_slug,
    started_at,
    ended_at,
    metadata
FROM neg_risk_stream_sessions
WHERE session_id = :session_id
  AND mode = 'SHADOW'
  AND NOT live_orders_enabled
""".strip()

_SELECT_REPLAY_MESSAGES_SQL = """
SELECT
    connection_epoch,
    message_sequence,
    received_at,
    payload
FROM neg_risk_stream_messages
WHERE session_id = :session_id
ORDER BY connection_epoch, message_sequence
LIMIT :maximum_messages
""".strip()


class ObservationRepositoryError(RuntimeError):
    """A value-safe persistence failure."""


@dataclass(frozen=True)
class StreamSessionStart:
    event_id: str
    event_slug: str
    market_count: int
    asset_count: int
    started_at: datetime
    metadata: Mapping[str, object]
    session_id: UUID | None = None

    def __post_init__(self) -> None:
        if not str(self.event_id or "").strip():
            raise ValueError("event_id is required")
        if not str(self.event_slug or "").strip():
            raise ValueError("event_slug is required")
        if self.market_count < 2 or self.asset_count < 4:
            raise ValueError("stream session counts are invalid")
        _aware_datetime(self.started_at, name="started_at")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


@dataclass(frozen=True)
class RecordedStreamMessage:
    connection_epoch: int
    message_sequence: int
    received_at: datetime
    payload: object
    updates: tuple[StreamUpdate, ...]
    route_evaluation: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.connection_epoch <= 0:
            raise ValueError("connection_epoch must be positive")
        if self.message_sequence <= 0:
            raise ValueError("message_sequence must be positive")
        _aware_datetime(self.received_at, name="received_at")
        updates = tuple(self.updates)
        if not updates:
            raise ValueError("updates are required")
        object.__setattr__(self, "updates", updates)
        payload = _json_dumps(self.payload)
        if len(payload.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("stream payload is too large")
        if (
            self.route_evaluation is not None
            and not isinstance(self.route_evaluation, Mapping)
        ):
            raise ValueError(
                "route_evaluation must be a mapping"
            )


@dataclass(frozen=True)
class ReplaySession:
    session_id: UUID
    event_id: str
    event_slug: str
    started_at: datetime
    ended_at: datetime | None
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        _aware_datetime(self.started_at, name="started_at")
        if self.ended_at is not None:
            _aware_datetime(self.ended_at, name="ended_at")
        if not str(self.event_id or "").strip():
            raise ValueError("event_id is required")
        if not str(self.event_slug or "").strip():
            raise ValueError("event_slug is required")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


@dataclass(frozen=True)
class ReplayMessage:
    connection_epoch: int
    message_sequence: int
    received_at: datetime
    payload: object

    def __post_init__(self) -> None:
        if self.connection_epoch <= 0:
            raise ValueError("connection_epoch must be positive")
        if self.message_sequence <= 0:
            raise ValueError("message_sequence must be positive")
        _aware_datetime(self.received_at, name="received_at")


class SqlAlchemyObservationRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        session_factory: Callable[[], Any] | None = None,
        text_factory: Callable[[str], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip() or None
        self._session_factory = session_factory
        self._text_factory = text_factory
        self._engine: Any | None = None

    def migrate(self) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            sql = _MIGRATION_PATH.read_text(encoding="utf-8")
            with session_factory() as session:
                session.execute(text_factory(sql))
                session.commit()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to migrate neg-risk observation schema: "
                f"{type(exc).__name__}"
            ) from None

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
                session.rollback()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to verify neg-risk observation schema: "
                f"{type(exc).__name__}"
            ) from None
        missing = [
            str(name)
            for name, present in row.items()
            if present is not True
        ]
        if missing:
            raise ObservationRepositoryError(
                "Neg-risk observation schema is incomplete: "
                + ",".join(sorted(missing))
            )

    def start_session(
        self,
        start: StreamSessionStart,
    ) -> UUID:
        session_id = start.session_id or uuid4()
        params = {
            "session_id": str(session_id),
            "event_id": str(start.event_id).strip(),
            "event_slug": str(start.event_slug).strip(),
            "market_count": int(start.market_count),
            "asset_count": int(start.asset_count),
            "started_at": start.started_at,
            "metadata": _json_dumps(dict(start.metadata)),
        }
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_INSERT_SESSION_SQL),
                    params,
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to start neg-risk stream session: "
                f"{type(exc).__name__}"
            ) from None
        return UUID(str(row["session_id"]))

    def append_batch(
        self,
        *,
        session_id: UUID,
        messages: Sequence[RecordedStreamMessage],
    ) -> int:
        batch = tuple(messages)
        if not batch:
            return 0
        session_factory, text_factory = self._dependencies()
        inserted_count = 0
        inserted_updates = 0
        became_ready = False
        last_message_at = batch[0].received_at
        try:
            with session_factory() as session:
                for message in batch:
                    params = _message_params(
                        session_id=session_id,
                        message=message,
                    )
                    row = session.execute(
                        text_factory(_INSERT_MESSAGE_SQL),
                        params,
                    ).mappings().one_or_none()
                    created = row is not None
                    if row is None:
                        row = session.execute(
                            text_factory(_SELECT_MESSAGE_SQL),
                            {
                                "session_id": str(session_id),
                                "connection_epoch": (
                                    message.connection_epoch
                                ),
                                "message_sequence": (
                                    message.message_sequence
                                ),
                            },
                        ).mappings().one()
                    message_id = int(row["id"])
                    route_params = _route_params(
                        session_id=session_id,
                        message_id=message_id,
                        message=message,
                    )
                    if route_params:
                        session.execute(
                            text_factory(_INSERT_ROUTE_SQL),
                            route_params,
                        )
                    if created:
                        inserted_count += 1
                        inserted_updates += len(message.updates)
                        became_ready = (
                            became_ready
                            or any(
                                update.became_ready
                                for update in message.updates
                            )
                        )
                        last_message_at = max(
                            last_message_at,
                            message.received_at,
                        )
                if inserted_count:
                    session.execute(
                        text_factory(_TOUCH_SESSION_SQL),
                        {
                            "session_id": str(session_id),
                            "became_ready": became_ready,
                            "last_message_at": last_message_at,
                            "message_count": inserted_count,
                            "update_count": inserted_updates,
                        },
                    )
                session.commit()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to append neg-risk observations: "
                f"{type(exc).__name__}"
            ) from None
        return inserted_count

    def mark_reconnecting(
        self,
        *,
        session_id: UUID,
        reason_code: str,
        connection_epoch: int,
        observed_at: datetime,
        diagnostics: Mapping[str, object] | None = None,
    ) -> None:
        if connection_epoch <= 0:
            raise ValueError("connection_epoch must be positive")
        _aware_datetime(observed_at, name="observed_at")
        params = {
            "session_id": str(session_id),
            "reason_code": _reason(reason_code),
            "connection_epoch": int(connection_epoch),
            "observed_at": observed_at,
            "diagnostics": _json_dumps(
                _safe_diagnostics(diagnostics or {})
            ),
        }
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(_INSERT_ANOMALY_SQL),
                    params,
                )
                session.execute(
                    text_factory(_RECONNECT_SESSION_SQL),
                    params,
                )
                session.commit()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to mark neg-risk stream reconnecting: "
                f"{type(exc).__name__}"
            ) from None

    def finish_session(
        self,
        *,
        session_id: UUID,
        status: str,
        reason_code: str | None,
        ended_at: datetime,
    ) -> None:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in {
            "STOPPED",
            "ERROR",
            "HALTED",
        }:
            raise ValueError("terminal session status is invalid")
        _aware_datetime(ended_at, name="ended_at")
        self._update_session(
            _FINISH_SESSION_SQL,
            {
                "session_id": str(session_id),
                "status": normalized_status,
                "ended_at": ended_at,
                "reason_code": (
                    _reason(reason_code)
                    if reason_code
                    else None
                ),
            },
            action="finish neg-risk stream session",
        )

    def load_replay_session(
        self,
        *,
        session_id: UUID | None = None,
    ) -> ReplaySession:
        session_factory, text_factory = self._dependencies()
        sql = (
            _SELECT_LATEST_REPLAY_SESSION_SQL
            if session_id is None
            else _SELECT_REPLAY_SESSION_SQL
        )
        params = (
            {}
            if session_id is None
            else {"session_id": str(session_id)}
        )
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(sql),
                    params,
                ).mappings().one_or_none()
                session.rollback()
        except Exception as exc:
            raise ObservationRepositoryError(
                "Failed to load neg-risk replay session: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            raise ObservationRepositoryError(
                "Neg-risk replay session was not found"
            )
        metadata = row["metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                raise ObservationRepositoryError(
                    "Neg-risk replay session metadata is invalid"
                ) from None
        if not isinstance(metadata, Mapping):
            raise ObservationRepositoryError(
                "Neg-risk replay session metadata is invalid"
            )
        return ReplaySession(
            session_id=UUID(str(row["session_id"])),
            event_id=str(row["event_id"]),
            event_slug=str(row["event_slug"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            metadata=dict(metadata),
        )

    def iter_replay_messages(
        self,
        *,
        session_id: UUID,
        maximum_messages: int | None = None,
    ) -> Iterable[ReplayMessage]:
        if maximum_messages is not None and maximum_messages <= 0:
            raise ValueError("maximum_messages must be positive")
        limit = (
            int(maximum_messages)
            if maximum_messages is not None
            else 9_223_372_036_854_775_807
        )
        session_factory, text_factory = self._dependencies()

        def rows() -> Iterable[ReplayMessage]:
            try:
                with session_factory() as session:
                    statement = text_factory(
                        _SELECT_REPLAY_MESSAGES_SQL
                    )
                    execution_options = getattr(
                        statement,
                        "execution_options",
                        None,
                    )
                    if callable(execution_options):
                        statement = execution_options(
                            stream_results=True,
                            yield_per=1_000,
                        )
                    result = session.execute(
                        statement,
                        {
                            "session_id": str(session_id),
                            "maximum_messages": limit,
                        },
                    ).mappings()
                    for row in result:
                        yield ReplayMessage(
                            connection_epoch=int(
                                row["connection_epoch"]
                            ),
                            message_sequence=int(
                                row["message_sequence"]
                            ),
                            received_at=row["received_at"],
                            payload=row["payload"],
                        )
                    session.rollback()
            except ObservationRepositoryError:
                raise
            except Exception as exc:
                raise ObservationRepositoryError(
                    "Failed to stream neg-risk replay messages: "
                    f"{type(exc).__name__}"
                ) from None

        return rows()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _update_session(
        self,
        sql: str,
        params: Mapping[str, object],
        *,
        action: str,
    ) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(sql), dict(params))
                session.commit()
        except Exception as exc:
            raise ObservationRepositoryError(
                f"Failed to {action}: {type(exc).__name__}"
            ) from None

    def _dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise ObservationRepositoryError(
                    "Neg-risk observation database is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise ObservationRepositoryError(
                    "Neg-risk persistence requires SQLAlchemy"
                ) from None
            try:
                normalized_url = _normalize_database_url(
                    self._database_url
                )
                connect_args: dict[str, object] = {}
                if normalized_url.startswith(
                    (
                        "postgresql://",
                        "postgresql+psycopg2://",
                    )
                ):
                    connect_args["application_name"] = (
                        "codexpoly_neg_risk_shadow"
                    )
                self._engine = create_engine(
                    normalized_url,
                    pool_size=1,
                    max_overflow=0,
                    pool_timeout=5,
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                    connect_args=connect_args,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise ObservationRepositoryError(
                    "Failed to initialize neg-risk persistence: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise ObservationRepositoryError(
                    "Neg-risk persistence requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _message_params(
    *,
    session_id: UUID,
    message: RecordedStreamMessage,
) -> dict[str, object]:
    timestamps = [
        update.timestamp_ms
        for update in message.updates
        if update.timestamp_ms is not None
    ]
    payload_json = _json_dumps(message.payload)
    return {
        "session_id": str(session_id),
        "connection_epoch": message.connection_epoch,
        "message_sequence": message.message_sequence,
        "received_at": message.received_at,
        "server_timestamp_min_ms": (
            min(timestamps) if timestamps else None
        ),
        "server_timestamp_max_ms": (
            max(timestamps) if timestamps else None
        ),
        "event_types": _json_dumps(
            sorted(
                {
                    update.event_type
                    for update in message.updates
                }
            )
        ),
        "affected_asset_ids": _json_dumps(
            sorted(
                {
                    asset_id
                    for update in message.updates
                    for asset_id in update.affected_asset_ids
                }
            )
        ),
        "payload": payload_json,
        "payload_bytes": len(payload_json.encode("utf-8")),
        "event_count": len(message.updates),
    }


def _route_params(
    *,
    session_id: UUID,
    message_id: int,
    message: RecordedStreamMessage,
) -> list[dict[str, object]]:
    evaluation = message.route_evaluation
    if evaluation is None:
        return []
    routes: list[Mapping[str, Any]] = []
    for name in ("available_routes", "unavailable_routes"):
        value = evaluation.get(name, [])
        if not isinstance(value, list):
            raise ValueError("route evaluation list is invalid")
        for route in value:
            if not isinstance(route, Mapping):
                raise ValueError("route evaluation row is invalid")
            routes.append(route)
    trigger_event_type = ",".join(
        sorted(
            {
                update.event_type
                for update in message.updates
            }
        )
    )
    params: list[dict[str, object]] = []
    for route in routes:
        available = route.get("available") is True
        try:
            route_direction = RouteDirection(
                str(route.get("route_direction") or "")
            )
        except ValueError as exc:
            raise ValueError(
                "route direction is invalid"
            ) from exc
        reward = route.get("reward")
        reward_mapping = (
            reward if isinstance(reward, Mapping) else {}
        )
        params.append(
            {
                "session_id": str(session_id),
                "stream_message_id": message_id,
                "connection_epoch": message.connection_epoch,
                "observed_at": message.received_at,
                "trigger_event_type": trigger_event_type,
                "route_direction": route_direction.value,
                "maker_condition_id": str(
                    route.get("maker_condition_id") or ""
                ),
                "maker_question": str(
                    route.get("maker_question") or ""
                ),
                "quantity": route.get("quantity"),
                "available": available,
                "reason_code": (
                    None
                    if available
                    else _reason(route.get("reason_code"))
                ),
                "maker_price": (
                    route.get("maker_price")
                    if available
                    else None
                ),
                "queue_ahead": (
                    route.get("queue_ahead")
                    if available
                    else None
                ),
                "gross_collateral": (
                    route.get("gross_collateral")
                    if available
                    else None
                ),
                "conservative_taker_fees": (
                    route.get("conservative_taker_fees")
                    if available
                    else None
                ),
                "base_profit": (
                    route.get("base_profit")
                    if available
                    else None
                ),
                "base_edge_per_share": (
                    route.get("base_edge_per_share")
                    if available
                    else None
                ),
                "estimated_maker_rebate": (
                    route.get("estimated_maker_rebate")
                    if available
                    else None
                ),
                "profit_with_rebate": (
                    route.get("profit_with_rebate")
                    if available
                    else None
                ),
                "edge_with_rebate_per_share": (
                    route.get("edge_with_rebate_per_share")
                    if available
                    else None
                ),
                "reward_top_of_book_candidate": (
                    reward_mapping.get(
                        "top_of_book_candidate"
                    )
                    if available
                    else None
                ),
                "hedge_legs": _json_dumps(
                    route.get("hedge_legs", [])
                    if available
                    else []
                ),
            }
        )
    return params


def _reason(value: object) -> str:
    reason = str(value or "").strip()
    if not reason:
        raise ValueError("reason_code is required")
    return reason[:160]


_DIAGNOSTIC_KEYS = frozenset(
    {
        "asset_id",
        "change_count",
        "condition_id",
        "epoch_reached_ready",
        "event_type",
        "expected_ask",
        "expected_bid",
        "local_ask",
        "local_bid",
        "reconnect_delay_seconds",
        "timestamp_ms",
    }
)


def _safe_diagnostics(
    value: Mapping[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if normalized_key not in _DIAGNOSTIC_KEYS:
            continue
        if item is None or isinstance(
            item,
            (bool, int, float),
        ):
            result[normalized_key] = item
        elif isinstance(item, str):
            result[normalized_key] = item[:160]
    return result


def _aware_datetime(value: datetime, *, name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")


def _json_dumps(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
