from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cbr_trading.domain.intents import OrderLifecyclePolicy
from cbr_trading.domain.results import ExecutionHandle, PlacedOrder
from cbr_trading.execution.order_group_state import (
    OrderGroupRecord,
    OrderGroupRegistration,
    OrderGroupStatus,
    SupervisionClaim,
    registration_from_handle,
)
from cbr_trading.execution.order_supervisor import TickSizeChange
from cbr_trading.execution.supervision_gateway import (
    OrderObservation,
)
from cbr_trading.secret_guard import redact_sensitive_text


_MIGRATION_PATHS = (
    (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "001_add_order_supervision_tables.sql"
    ),
    (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "002_add_order_observations.sql"
    ),
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_order_groups') IS NOT NULL
        AS groups_table,
    (
        SELECT count(*) = 24
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_order_groups'
          AND column_name = ANY(ARRAY[
              'order_group_id', 'intent_id', 'signal_id', 'template_id',
              'strategy_id', 'account_name', 'condition_id', 'outcome',
              'asset_id', 'side', 'desired_price', 'quantity', 'notional',
              'policy_kind', 'trigger_old_tick', 'trigger_new_tick',
              'max_reprices', 'reprice_count', 'status', 'revision',
              'last_error', 'metadata', 'created_at', 'updated_at'
          ])
    ) AS groups_columns,
    to_regclass('resolution_order_group_orders') IS NOT NULL
        AS orders_table,
    (
        SELECT count(*) = 12
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_order_group_orders'
          AND column_name = ANY(ARRAY[
              'id', 'order_group_id', 'order_id', 'generation', 'status',
              'effective_price', 'quantity', 'parent_order_id', 'metadata',
              'opened_at', 'closed_at', 'updated_at'
          ])
    ) AS orders_columns,
    to_regclass('resolution_supervision_events') IS NOT NULL
        AS events_table,
    (
        SELECT count(*) = 13
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_supervision_events'
          AND column_name = ANY(ARRAY[
              'event_id', 'order_group_id', 'event_type', 'status',
              'asset_id', 'old_tick', 'new_tick', 'observed_at',
              'claimed_revision', 'error', 'payload', 'created_at',
              'updated_at'
          ])
    ) AS events_columns,
    to_regclass('resolution_order_observations') IS NOT NULL
        AS observations_table,
    (
        SELECT count(*) = 15
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_order_observations'
          AND column_name = ANY(ARRAY[
              'event_id', 'order_group_id', 'order_id', 'phase',
              'condition_id', 'asset_id', 'side', 'remote_state',
              'remote_status', 'original_quantity', 'matched_quantity',
              'remaining_quantity', 'limit_price', 'observed_at',
              'created_at'
          ])
    ) AS observations_columns
""".strip()

_INSERT_GROUP_SQL = """
INSERT INTO resolution_order_groups (
    order_group_id,
    intent_id,
    signal_id,
    template_id,
    strategy_id,
    account_name,
    condition_id,
    outcome,
    asset_id,
    side,
    desired_price,
    quantity,
    notional,
    policy_kind,
    trigger_old_tick,
    trigger_new_tick,
    max_reprices,
    metadata
)
VALUES (
    :order_group_id,
    :intent_id,
    :signal_id,
    :template_id,
    :strategy_id,
    :account_name,
    :condition_id,
    :outcome,
    :asset_id,
    :side,
    :desired_price,
    :quantity,
    :notional,
    :policy_kind,
    :trigger_old_tick,
    :trigger_new_tick,
    :max_reprices,
    CAST(:metadata AS jsonb)
)
ON CONFLICT (order_group_id) DO NOTHING
RETURNING order_group_id
""".strip()

_INSERT_ORDER_SQL = """
INSERT INTO resolution_order_group_orders (
    order_group_id,
    order_id,
    generation,
    status,
    quantity
)
VALUES (
    :order_group_id,
    :order_id,
    0,
    'LIVE',
    :quantity
)
""".strip()

_SELECT_GROUP_SQL = """
SELECT
    groups.order_group_id,
    groups.intent_id,
    groups.signal_id,
    groups.template_id,
    groups.strategy_id,
    groups.account_name,
    groups.condition_id,
    groups.outcome,
    groups.asset_id,
    groups.side,
    groups.desired_price,
    groups.quantity,
    groups.notional,
    groups.policy_kind,
    groups.trigger_old_tick,
    groups.trigger_new_tick,
    groups.max_reprices,
    groups.reprice_count,
    groups.status,
    groups.revision,
    groups.last_error,
    groups.metadata,
    groups.created_at,
    groups.updated_at,
    COALESCE(
        array_agg(orders.order_id ORDER BY orders.id)
            FILTER (WHERE orders.generation = 0),
        ARRAY[]::text[]
    ) AS initial_order_ids,
    COALESCE(
        array_agg(orders.order_id ORDER BY orders.id)
            FILTER (WHERE orders.status = 'LIVE'),
        ARRAY[]::text[]
    ) AS live_order_ids
FROM resolution_order_groups AS groups
LEFT JOIN resolution_order_group_orders AS orders
  ON orders.order_group_id = groups.order_group_id
WHERE groups.order_group_id = :order_group_id
GROUP BY groups.order_group_id
""".strip()

_SELECT_ACTIVE_FOR_ASSET_SQL = (
    _SELECT_GROUP_SQL.replace(
        "WHERE groups.order_group_id = :order_group_id",
        (
            "WHERE groups.asset_id = :asset_id "
            "AND groups.status = 'ACTIVE'"
        ),
    )
)

_INSERT_EVENT_SQL = """
INSERT INTO resolution_supervision_events (
    event_id,
    order_group_id,
    event_type,
    status,
    asset_id,
    old_tick,
    new_tick,
    observed_at,
    payload
)
VALUES (
    :event_id,
    :order_group_id,
    'tick_size_change',
    'RECEIVED',
    :asset_id,
    :old_tick,
    :new_tick,
    :observed_at,
    CAST(:payload AS jsonb)
)
ON CONFLICT (event_id, order_group_id) DO NOTHING
RETURNING status
""".strip()

_SELECT_EVENT_SQL = """
SELECT status
FROM resolution_supervision_events
WHERE event_id = :event_id
  AND order_group_id = :order_group_id
""".strip()

_CLAIM_GROUP_SQL = """
UPDATE resolution_order_groups
SET
    status = 'REPRICING',
    revision = revision + 1,
    last_error = NULL,
    updated_at = now()
WHERE order_group_id = :order_group_id
  AND asset_id = :asset_id
  AND status = 'ACTIVE'
  AND policy_kind = 'reprice_on_tick_change'
  AND trigger_old_tick = :old_tick
  AND trigger_new_tick = :new_tick
  AND reprice_count < max_reprices
RETURNING revision
""".strip()

_MARK_EVENT_CLAIMED_SQL = """
UPDATE resolution_supervision_events
SET
    status = 'CLAIMED',
    claimed_revision = :revision,
    updated_at = now()
WHERE event_id = :event_id
  AND order_group_id = :order_group_id
  AND status = 'RECEIVED'
""".strip()

_MARK_EVENT_IGNORED_SQL = """
UPDATE resolution_supervision_events
SET
    status = 'IGNORED',
    error = :reason,
    updated_at = now()
WHERE event_id = :event_id
  AND order_group_id = :order_group_id
  AND status = 'RECEIVED'
""".strip()

_COMPLETE_GROUP_SQL = """
UPDATE resolution_order_groups
SET
    reprice_count = reprice_count + 1,
    status = CASE
        WHEN reprice_count + 1 >= max_reprices THEN 'COMPLETED'
        ELSE 'ACTIVE'
    END,
    revision = revision + 1,
    last_error = NULL,
    updated_at = now()
WHERE order_group_id = :order_group_id
  AND status = 'REPRICING'
  AND revision = :revision
RETURNING reprice_count, status, revision
""".strip()

_COMPLETE_WITHOUT_REPLACEMENT_GROUP_SQL = """
UPDATE resolution_order_groups
SET
    status = 'COMPLETED',
    revision = revision + 1,
    last_error = NULL,
    updated_at = now()
WHERE order_group_id = :order_group_id
  AND status = 'REPRICING'
  AND revision = :revision
RETURNING revision
""".strip()

_CLOSE_OWNED_ORDERS_SQL = """
UPDATE resolution_order_group_orders
SET
    status = :status,
    closed_at = now(),
    updated_at = now()
WHERE order_group_id = :order_group_id
  AND status = 'LIVE'
  AND order_id = ANY(:order_ids)
RETURNING order_id
""".strip()

_INSERT_REPLACEMENT_ORDER_SQL = """
INSERT INTO resolution_order_group_orders (
    order_group_id,
    order_id,
    generation,
    status,
    effective_price,
    quantity,
    parent_order_id,
    metadata
)
VALUES (
    :order_group_id,
    :order_id,
    :generation,
    :status,
    :effective_price,
    :quantity,
    :parent_order_id,
    CAST(:metadata AS jsonb)
)
""".strip()

_INSERT_OBSERVATION_SQL = """
INSERT INTO resolution_order_observations (
    event_id,
    order_group_id,
    order_id,
    phase,
    condition_id,
    asset_id,
    side,
    remote_state,
    remote_status,
    limit_price,
    original_quantity,
    matched_quantity,
    remaining_quantity,
    observed_at
)
VALUES (
    :event_id,
    :order_group_id,
    :order_id,
    :phase,
    :condition_id,
    :asset_id,
    :side,
    :remote_state,
    :remote_status,
    :limit_price,
    :original_quantity,
    :matched_quantity,
    :remaining_quantity,
    :observed_at
)
ON CONFLICT (
    event_id,
    order_group_id,
    order_id,
    phase
) DO NOTHING
""".strip()

_COMPLETE_EVENT_SQL = """
UPDATE resolution_supervision_events
SET
    status = 'COMPLETED',
    error = NULL,
    updated_at = now()
WHERE event_id = :event_id
  AND order_group_id = :order_group_id
  AND status = 'CLAIMED'
  AND claimed_revision = :revision
""".strip()

_FAIL_GROUP_SQL = """
UPDATE resolution_order_groups
SET
    status = 'FAILED',
    revision = revision + 1,
    last_error = :error,
    updated_at = now()
WHERE order_group_id = :order_group_id
  AND status = 'REPRICING'
  AND revision = :revision
RETURNING reprice_count + 1 AS failed_generation
""".strip()

_FAIL_EVENT_SQL = """
UPDATE resolution_supervision_events
SET
    status = 'FAILED',
    error = :error,
    updated_at = now()
WHERE event_id = :event_id
  AND order_group_id = :order_group_id
  AND status = 'CLAIMED'
  AND claimed_revision = :revision
""".strip()


class OrderGroupRepositoryError(RuntimeError):
    """Sanitized persistence failure for order supervision state."""


class SqlAlchemyOrderGroupRepository:
    """Additive storage for owned order groups and supervision events."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        session_factory: Callable[[], Any] | None = None,
        text_factory: Callable[[str], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._session_factory = session_factory
        self._text_factory = text_factory
        self._engine: Any | None = None

    def migrate(self) -> None:
        """Create only the new supervision tables and indexes."""

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                for path in _MIGRATION_PATHS:
                    migration_sql = path.read_text(
                        encoding="utf-8"
                    )
                    session.execute(text_factory(migration_sql))
                session.commit()
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to apply additive order supervision migration: "
                f"{type(exc).__name__}"
            ) from exc

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to verify order supervision schema: "
                f"{type(exc).__name__}"
            ) from exc

        if not all(
            bool(row.get(name))
            for name in (
                "groups_table",
                "groups_columns",
                "orders_table",
                "orders_columns",
                "events_table",
                "events_columns",
                "observations_table",
                "observations_columns",
            )
        ):
            raise OrderGroupRepositoryError(
                "Order supervision tables are not ready"
            )

    def register(
        self,
        handle: ExecutionHandle,
        *,
        policy: OrderLifecyclePolicy,
        metadata: Mapping[str, Any] | None = None,
    ) -> OrderGroupRecord:
        registration = registration_from_handle(
            handle,
            policy=policy,
            metadata=metadata,
        )
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_GROUP_SQL),
                    _registration_params(registration),
                ).mappings().one_or_none()
                if inserted is not None:
                    for order_id in registration.initial_order_ids:
                        session.execute(
                            text_factory(_INSERT_ORDER_SQL),
                            {
                                "order_group_id": (
                                    registration.order_group_id
                                ),
                                "order_id": order_id,
                                "quantity": registration.quantity,
                            },
                        )

                row = session.execute(
                    text_factory(_SELECT_GROUP_SQL),
                    {
                        "order_group_id": (
                            registration.order_group_id
                        )
                    },
                ).mappings().one()
                record = _record_from_row(row)
                if record.registration != registration:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Order group registration conflicts with "
                        "existing ownership"
                    )
                session.commit()
                return record
        except OrderGroupRepositoryError:
            raise
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to register order group: "
                f"{type(exc).__name__}"
            ) from exc

    def load_active_for_asset(
        self,
        asset_id: str,
    ) -> tuple[OrderGroupRecord, ...]:
        normalized_asset = str(asset_id or "").strip()
        if not normalized_asset:
            raise ValueError("asset_id is required")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_SELECT_ACTIVE_FOR_ASSET_SQL),
                    {"asset_id": normalized_asset},
                ).mappings().all()
            return tuple(_record_from_row(row) for row in rows)
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to load active order groups: "
                f"{type(exc).__name__}"
            ) from exc

    def claim_tick_size_change(
        self,
        *,
        order_group_id: str,
        event: TickSizeChange,
    ) -> SupervisionClaim:
        normalized_group = str(order_group_id or "").strip()
        if not normalized_group:
            raise ValueError("order_group_id is required")
        params = _event_params(
            order_group_id=normalized_group,
            event=event,
        )
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_EVENT_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is None:
                    existing = session.execute(
                        text_factory(_SELECT_EVENT_SQL),
                        params,
                    ).mappings().one()
                    session.rollback()
                    return SupervisionClaim(
                        event_id=event.event_id,
                        order_group_id=normalized_group,
                        acquired=False,
                        reason=(
                            "duplicate_event:"
                            f"{str(existing.get('status') or 'unknown').lower()}"
                        ),
                    )

                claimed = session.execute(
                    text_factory(_CLAIM_GROUP_SQL),
                    params,
                ).mappings().one_or_none()
                if claimed is None:
                    session.execute(
                        text_factory(_MARK_EVENT_IGNORED_SQL),
                        {
                            **params,
                            "reason": "order_group_not_claimable",
                        },
                    )
                    session.commit()
                    return SupervisionClaim(
                        event_id=event.event_id,
                        order_group_id=normalized_group,
                        acquired=False,
                        reason="order_group_not_claimable",
                    )

                revision = int(claimed["revision"])
                marked = session.execute(
                    text_factory(_MARK_EVENT_CLAIMED_SQL),
                    {**params, "revision": revision},
                )
                if int(marked.rowcount or 0) != 1:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision event claim was not persisted"
                    )
                session.commit()
                return SupervisionClaim(
                    event_id=event.event_id,
                    order_group_id=normalized_group,
                    acquired=True,
                    revision=revision,
                )
        except OrderGroupRepositoryError:
            raise
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to claim tick-size event: "
                f"{type(exc).__name__}"
            ) from exc

    def fail_claim(
        self,
        claim: SupervisionClaim,
        *,
        error: str,
        cancelled_order_ids: Sequence[str] = (),
        filled_order_ids: Sequence[str] = (),
        replacement_orders: Sequence[PlacedOrder] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None:
        if not claim.acquired or claim.revision is None:
            raise ValueError("only an acquired supervision claim can fail")
        safe_error = redact_sensitive_text(error, max_length=500)
        if not safe_error:
            raise ValueError("error is required")
        cancelled = _normalized_order_ids(
            cancelled_order_ids,
            name="cancelled_order_ids",
            required=False,
        )
        filled = _normalized_order_ids(
            filled_order_ids,
            name="filled_order_ids",
            required=False,
        )
        _require_disjoint_order_ids(
            cancelled,
            filled,
        )
        replacements = _validated_replacement_orders(
            replacement_orders,
            required=False,
        )
        inspected = _validated_observations(observations)
        params = {
            "event_id": claim.event_id,
            "order_group_id": claim.order_group_id,
            "revision": claim.revision,
            "error": safe_error,
        }
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                failed_group = session.execute(
                    text_factory(_FAIL_GROUP_SQL),
                    params,
                ).mappings().one_or_none()
                if failed_group is None:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision claim is no longer current"
                    )
                generation = int(failed_group["failed_generation"])

                _persist_observations(
                    session,
                    text_factory=text_factory,
                    claim=claim,
                    observations=inspected,
                )
                if filled:
                    _close_owned_orders(
                        session,
                        text_factory=text_factory,
                        params=params,
                        order_ids=filled,
                        status="FILLED",
                    )
                if cancelled:
                    _close_owned_orders(
                        session,
                        text_factory=text_factory,
                        params=params,
                        order_ids=cancelled,
                        status="CANCELLED",
                    )

                parent_order_id = (
                    cancelled[0]
                    if len(cancelled) == 1
                    else None
                )
                for replacement in replacements:
                    session.execute(
                        text_factory(_INSERT_REPLACEMENT_ORDER_SQL),
                        _replacement_params(
                            claim=claim,
                            replacement=replacement,
                            generation=generation,
                            status="UNKNOWN",
                            parent_order_id=parent_order_id,
                        ),
                    )

                event_result = session.execute(
                    text_factory(_FAIL_EVENT_SQL),
                    params,
                )
                if int(event_result.rowcount or 0) != 1:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision claim is no longer current"
                    )
                session.commit()
        except OrderGroupRepositoryError:
            raise
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to mark supervision claim failed: "
                f"{type(exc).__name__}"
            ) from exc

    def complete_reprice(
        self,
        claim: SupervisionClaim,
        *,
        cancelled_order_ids: Sequence[str],
        replacement_orders: Sequence[PlacedOrder],
        filled_order_ids: Sequence[str] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None:
        if not claim.acquired or claim.revision is None:
            raise ValueError(
                "only an acquired supervision claim can complete"
            )
        cancelled = _normalized_order_ids(
            cancelled_order_ids,
            name="cancelled_order_ids",
            required=True,
        )
        filled = _normalized_order_ids(
            filled_order_ids,
            name="filled_order_ids",
            required=False,
        )
        _require_disjoint_order_ids(
            cancelled,
            filled,
        )
        replacements = _validated_replacement_orders(
            replacement_orders,
            required=True,
        )
        inspected = _validated_observations(observations)
        params = {
            "event_id": claim.event_id,
            "order_group_id": claim.order_group_id,
            "revision": claim.revision,
        }
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                completed_group = session.execute(
                    text_factory(_COMPLETE_GROUP_SQL),
                    params,
                ).mappings().one_or_none()
                if completed_group is None:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision claim is no longer current"
                    )
                generation = int(completed_group["reprice_count"])

                _persist_observations(
                    session,
                    text_factory=text_factory,
                    claim=claim,
                    observations=inspected,
                )
                if filled:
                    _close_owned_orders(
                        session,
                        text_factory=text_factory,
                        params=params,
                        order_ids=filled,
                        status="FILLED",
                    )
                _close_owned_orders(
                    session,
                    text_factory=text_factory,
                    params=params,
                    order_ids=cancelled,
                    status="REPLACED",
                )

                parent_order_id = (
                    cancelled[0]
                    if len(cancelled) == 1
                    else None
                )
                for replacement in replacements:
                    session.execute(
                        text_factory(_INSERT_REPLACEMENT_ORDER_SQL),
                        _replacement_params(
                            claim=claim,
                            replacement=replacement,
                            generation=generation,
                            status="LIVE",
                            parent_order_id=parent_order_id,
                        ),
                    )

                completed_event = session.execute(
                    text_factory(_COMPLETE_EVENT_SQL),
                    params,
                )
                if int(completed_event.rowcount or 0) != 1:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision event completion was not persisted"
                    )
                session.commit()
        except OrderGroupRepositoryError:
            raise
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to complete order repricing: "
                f"{type(exc).__name__}"
            ) from exc

    def complete_without_replacement(
        self,
        claim: SupervisionClaim,
        *,
        filled_order_ids: Sequence[str],
        cancelled_order_ids: Sequence[str] = (),
        observations: Sequence[OrderObservation] = (),
    ) -> None:
        if not claim.acquired or claim.revision is None:
            raise ValueError(
                "only an acquired supervision claim can complete"
            )
        filled = _normalized_order_ids(
            filled_order_ids,
            name="filled_order_ids",
            required=False,
        )
        cancelled = _normalized_order_ids(
            cancelled_order_ids,
            name="cancelled_order_ids",
            required=False,
        )
        if not filled and not cancelled:
            raise ValueError(
                "filled or cancelled order ids are required"
            )
        _require_disjoint_order_ids(cancelled, filled)
        inspected = _validated_observations(observations)
        params = {
            "event_id": claim.event_id,
            "order_group_id": claim.order_group_id,
            "revision": claim.revision,
        }
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                completed = session.execute(
                    text_factory(
                        _COMPLETE_WITHOUT_REPLACEMENT_GROUP_SQL
                    ),
                    params,
                ).mappings().one_or_none()
                if completed is None:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision claim is no longer current"
                    )
                _persist_observations(
                    session,
                    text_factory=text_factory,
                    claim=claim,
                    observations=inspected,
                )
                if filled:
                    _close_owned_orders(
                        session,
                        text_factory=text_factory,
                        params=params,
                        order_ids=filled,
                        status="FILLED",
                    )
                if cancelled:
                    _close_owned_orders(
                        session,
                        text_factory=text_factory,
                        params=params,
                        order_ids=cancelled,
                        status="CANCELLED",
                    )
                completed_event = session.execute(
                    text_factory(_COMPLETE_EVENT_SQL),
                    params,
                )
                if int(completed_event.rowcount or 0) != 1:
                    session.rollback()
                    raise OrderGroupRepositoryError(
                        "Supervision event completion was not persisted"
                    )
                session.commit()
        except OrderGroupRepositoryError:
            raise
        except Exception as exc:
            raise OrderGroupRepositoryError(
                "Failed to complete filled order group: "
                f"{type(exc).__name__}"
            ) from exc

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise OrderGroupRepositoryError(
                    "Order supervision database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise OrderGroupRepositoryError(
                    "Order supervision requires SQLAlchemy"
                ) from exc
            try:
                self._engine = create_engine(
                    _normalize_database_url(self._database_url),
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise OrderGroupRepositoryError(
                    "Failed to initialize order supervision storage: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise OrderGroupRepositoryError(
                    "Order supervision requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def order_supervision_migration_sql() -> str:
    """Expose the reviewed additive SQL for deployment tooling and tests."""

    return "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in _MIGRATION_PATHS
    )


def _registration_params(
    registration: OrderGroupRegistration,
) -> dict[str, Any]:
    return {
        "order_group_id": registration.order_group_id,
        "intent_id": registration.intent_id,
        "signal_id": registration.signal_id,
        "template_id": registration.template_id,
        "strategy_id": registration.strategy_id,
        "account_name": registration.account_name,
        "condition_id": registration.condition_id,
        "outcome": registration.outcome.value,
        "asset_id": registration.asset_id,
        "side": (
            registration.side.value
            if registration.side is not None
            else None
        ),
        "desired_price": registration.desired_price,
        "quantity": registration.quantity,
        "notional": registration.notional,
        "policy_kind": registration.policy_kind,
        "trigger_old_tick": registration.trigger_old_tick,
        "trigger_new_tick": registration.trigger_new_tick,
        "max_reprices": registration.max_reprices,
        "metadata": json.dumps(
            dict(registration.metadata),
            ensure_ascii=False,
            default=str,
        ),
    }


def _event_params(
    *,
    order_group_id: str,
    event: TickSizeChange,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "order_group_id": order_group_id,
        "asset_id": event.asset_id,
        "old_tick": event.old_tick,
        "new_tick": event.new_tick,
        "observed_at": event.observed_at,
        "payload": json.dumps(
            {
                "event_id": event.event_id,
                "asset_id": event.asset_id,
                "old_tick": str(event.old_tick),
                "new_tick": str(event.new_tick),
                "observed_at": event.observed_at.isoformat(),
            },
            ensure_ascii=False,
        ),
    }


def _normalized_order_ids(
    values: Sequence[str],
    *,
    name: str,
    required: bool,
) -> tuple[str, ...]:
    normalized = tuple(
        str(value or "").strip()
        for value in values
    )
    if any(not value for value in normalized):
        raise ValueError(f"{name} cannot contain empty values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must be unique")
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _validated_replacement_orders(
    values: Sequence[PlacedOrder],
    *,
    required: bool,
) -> tuple[PlacedOrder, ...]:
    orders = tuple(values)
    if any(not isinstance(order, PlacedOrder) for order in orders):
        raise TypeError(
            "replacement_orders must contain PlacedOrder objects"
        )
    order_ids = [order.order_id for order in orders]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("replacement order ids must be unique")
    if required and not orders:
        raise ValueError("replacement_orders must not be empty")
    return orders


def _validated_observations(
    values: Sequence[OrderObservation],
) -> tuple[OrderObservation, ...]:
    observations = tuple(values)
    if any(
        not isinstance(observation, OrderObservation)
        for observation in observations
    ):
        raise TypeError(
            "observations must contain OrderObservation objects"
        )
    keys = [
        (
            observation.snapshot.order_id,
            observation.phase.value,
        )
        for observation in observations
    ]
    if len(keys) != len(set(keys)):
        raise ValueError(
            "order observation phase keys must be unique"
        )
    return observations


def _require_disjoint_order_ids(
    first: Sequence[str],
    second: Sequence[str],
) -> None:
    if set(first) & set(second):
        raise ValueError(
            "cancelled and filled order ids must be disjoint"
        )


def _close_owned_orders(
    session: Any,
    *,
    text_factory: Callable[[str], Any],
    params: Mapping[str, Any],
    order_ids: Sequence[str],
    status: str,
) -> None:
    closed = session.execute(
        text_factory(_CLOSE_OWNED_ORDERS_SQL),
        {
            **params,
            "status": status,
            "order_ids": list(order_ids),
        },
    ).mappings().all()
    try:
        _require_exact_closed_orders(
            closed,
            expected=order_ids,
        )
    except OrderGroupRepositoryError:
        session.rollback()
        raise


def _persist_observations(
    session: Any,
    *,
    text_factory: Callable[[str], Any],
    claim: SupervisionClaim,
    observations: Sequence[OrderObservation],
) -> None:
    for observation in observations:
        snapshot = observation.snapshot
        session.execute(
            text_factory(_INSERT_OBSERVATION_SQL),
            {
                "event_id": claim.event_id,
                "order_group_id": claim.order_group_id,
                "order_id": snapshot.order_id,
                "phase": observation.phase.value,
                "condition_id": snapshot.condition_id,
                "asset_id": snapshot.asset_id,
                "side": snapshot.side.value,
                "remote_state": snapshot.state.value,
                "remote_status": snapshot.remote_status,
                "limit_price": snapshot.limit_price,
                "original_quantity": snapshot.original_quantity,
                "matched_quantity": snapshot.matched_quantity,
                "remaining_quantity": snapshot.remaining_quantity,
                "observed_at": snapshot.observed_at,
            },
        )


def _require_exact_closed_orders(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected: Sequence[str],
) -> None:
    actual = {
        str(row.get("order_id") or "").strip()
        for row in rows
    }
    if actual != set(expected):
        raise OrderGroupRepositoryError(
            "Cancelled order ownership no longer matches the claim"
        )


def _replacement_params(
    *,
    claim: SupervisionClaim,
    replacement: PlacedOrder,
    generation: int,
    status: str,
    parent_order_id: str | None,
) -> dict[str, Any]:
    return {
        "order_group_id": claim.order_group_id,
        "order_id": replacement.order_id,
        "generation": generation,
        "status": status,
        "effective_price": replacement.effective_price,
        "quantity": replacement.quantity,
        "parent_order_id": parent_order_id,
        "metadata": json.dumps(
            {
                "event_id": claim.event_id,
                "claim_revision": claim.revision,
            },
            ensure_ascii=False,
        ),
    }


def _record_from_row(row: Mapping[str, Any]) -> OrderGroupRecord:
    registration = OrderGroupRegistration(
        order_group_id=row.get("order_group_id"),
        intent_id=row.get("intent_id"),
        signal_id=row.get("signal_id"),
        template_id=row.get("template_id"),
        strategy_id=row.get("strategy_id"),
        account_name=row.get("account_name"),
        condition_id=row.get("condition_id"),
        outcome=row.get("outcome"),
        asset_id=row.get("asset_id"),
        side=row.get("side"),
        desired_price=_decimal_or_none(row.get("desired_price")),
        quantity=_decimal_or_none(row.get("quantity")),
        notional=_decimal_or_none(row.get("notional")),
        policy_kind=row.get("policy_kind"),
        trigger_old_tick=_decimal_or_none(
            row.get("trigger_old_tick")
        ),
        trigger_new_tick=_decimal_or_none(
            row.get("trigger_new_tick")
        ),
        max_reprices=int(row.get("max_reprices") or 0),
        initial_order_ids=tuple(row.get("initial_order_ids") or ()),
        metadata=(
            row.get("metadata")
            if isinstance(row.get("metadata"), Mapping)
            else {}
        ),
    )
    return OrderGroupRecord(
        registration=registration,
        status=OrderGroupStatus(str(row.get("status")).upper()),
        revision=int(row.get("revision") or 0),
        reprice_count=int(row.get("reprice_count") or 0),
        live_order_ids=tuple(row.get("live_order_ids") or ()),
        last_error=row.get("last_error"),
        created_at=_datetime_or_none(row.get("created_at")),
        updated_at=_datetime_or_none(row.get("updated_at")),
    )


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
