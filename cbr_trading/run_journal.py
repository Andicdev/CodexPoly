from __future__ import annotations

from collections.abc import Callable
from typing import Any


_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_run_journal') IS NOT NULL
        AS journal_table,
    to_regclass('resolution_run_journal_events') IS NOT NULL
        AS event_table,
    to_regclass('ux_resolution_run_journal_key') IS NOT NULL
        AS journal_key_index,
    to_regclass('ux_resolution_run_journal_events_key') IS NOT NULL
        AS event_key_index
""".strip()

_RECONCILE_EARNINGS_SQL = """
WITH run AS (
    SELECT
        profile.scope_id,
        profile.profile_key,
        profile.source_reference AS market_url,
        profile.yes_desired_price,
        profile.no_desired_price,
        profile.quantity AS profile_quantity,
        schedule.schedule_key,
        schedule.activate_at,
        schedule.deactivate_at,
        schedule.state AS schedule_state,
        schedule.metadata ->> 'live_block' AS live_block,
        schedule.metadata ->> 'block_id' AS block_id,
        rule.comparison_op,
        rule.strike,
        fact.id AS fact_id,
        fact.value AS fact_value,
        fact.provider AS fact_provider,
        fact.published_at,
        fact.detected_at,
        source_event.id AS source_event_id,
        source_event.provider AS source_provider,
        source_event.source_url,
        source_event.filed_at,
        source_event.received_at,
        source_event.status AS source_status,
        claim.id AS claim_id,
        claim.outcome AS claim_outcome,
        claim.status AS claim_status,
        claim.desired_price AS claim_desired_price,
        claim.effective_price AS claim_effective_price,
        claim.quantity AS claim_quantity,
        claim.created_at AS claim_created_at,
        claim.completed_at AS claim_completed_at,
        orders.first_opened_at,
        orders.last_opened_at,
        orders.current_effective_price,
        orders.matched_quantity,
        orders.any_filled
    FROM resolution_execution_profiles AS profile
    JOIN resolution_profile_schedules AS schedule
      ON schedule.profile_key = profile.profile_key
    JOIN earnings_market_rules AS rule
      ON rule.scope_id = profile.scope_id
    LEFT JOIN LATERAL (
        SELECT candidate.*
        FROM earnings_fact_candidates AS candidate
        WHERE candidate.scope_id = profile.scope_id
          AND candidate.status IN ('VALIDATED', 'EMITTED')
        ORDER BY candidate.detected_at, candidate.id
        LIMIT 1
    ) AS fact ON true
    LEFT JOIN LATERAL (
        SELECT event.*
        FROM earnings_source_events AS event
        WHERE event.scope_id = profile.scope_id
          AND (
              fact.source_event_id IS NULL
              OR event.id = fact.source_event_id
          )
        ORDER BY
            CASE
                WHEN event.id = fact.source_event_id THEN 0
                ELSE 1
            END,
            event.received_at,
            event.id
        LIMIT 1
    ) AS source_event ON true
    LEFT JOIN LATERAL (
        SELECT execution.*
        FROM resolution_execution_claims AS execution
        WHERE execution.scope_id = profile.scope_id
          AND execution.status <> 'EXPIRED'
        ORDER BY
            CASE execution.status
                WHEN 'EXECUTED' THEN 0
                WHEN 'ERROR' THEN 1
                WHEN 'REJECTED' THEN 2
                ELSE 3
            END,
            execution.created_at,
            execution.id
        LIMIT 1
    ) AS claim ON true
    LEFT JOIN LATERAL (
        SELECT
            min(order_row.opened_at) AS first_opened_at,
            max(order_row.opened_at) AS last_opened_at,
            coalesce(
                max(order_row.effective_price)
                    FILTER (WHERE order_row.status = 'LIVE'),
                max(order_row.effective_price)
            ) AS current_effective_price,
            coalesce(max(observation.matched_quantity), 0)
                AS matched_quantity,
            bool_or(
                order_row.status = 'FILLED'
                OR coalesce(observation.matched_quantity, 0)
                    >= coalesce(
                        order_row.quantity,
                        profile.quantity
                    )
            ) AS any_filled
        FROM resolution_order_groups AS groups
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = groups.order_group_id
        LEFT JOIN resolution_order_observations AS observation
          ON observation.order_group_id = groups.order_group_id
         AND observation.order_id = order_row.order_id
        WHERE groups.condition_id = profile.condition_id
          AND groups.created_at >=
              schedule.activate_at - interval '15 minutes'
    ) AS orders ON true
    WHERE profile.source_name = 'earnings_resolution'
      AND schedule.activate_at <= now()
      AND schedule.activate_at >= now() - interval '36 hours'
      AND (
          fact.id IS NOT NULL
          OR source_event.status IN (
              'NO_MATCH',
              'QUARANTINED',
              'ERROR'
          )
          OR (
              schedule.state = 'EXPIRED'
              AND now() >= schedule.deactivate_at
          )
      )
),
classified AS (
    SELECT
        run.*,
        coalesce(
            claim_outcome,
            CASE
                WHEN fact_id IS NULL THEN NULL
                WHEN comparison_op = '>' AND fact_value > strike
                    THEN 'YES'
                WHEN comparison_op = '>=' AND fact_value >= strike
                    THEN 'YES'
                WHEN comparison_op = '<' AND fact_value < strike
                    THEN 'YES'
                WHEN comparison_op = '<=' AND fact_value <= strike
                    THEN 'YES'
                WHEN comparison_op = '==' AND fact_value = strike
                    THEN 'YES'
                ELSE 'NO'
            END
        ) AS selected_outcome,
        CASE
            WHEN claim_status = 'EXECUTED'
             AND (
                 any_filled
                 OR matched_quantity >= claim_quantity
             ) THEN 'FILLED'
            WHEN claim_status = 'EXECUTED'
             AND matched_quantity > 0 THEN 'PARTIALLY_FILLED'
            WHEN claim_status = 'EXECUTED' THEN 'ACCEPTED_OPEN'
            WHEN claim_status = 'REJECTED' THEN 'REJECTED'
            WHEN claim_status = 'ERROR' THEN 'ERROR'
            WHEN fact_id IS NOT NULL THEN 'NOT_ATTEMPTED'
            ELSE 'UNKNOWN'
        END AS execution_status,
        CASE
            WHEN claim_status = 'EXECUTED'
             AND (
                 any_filled
                 OR matched_quantity > 0
             ) THEN 'FAST'
            WHEN claim_status = 'EXECUTED'
             AND coalesce(
                 current_effective_price,
                 claim_effective_price
             ) >= 0.99 THEN 'TOO_SLOW'
            ELSE 'UNKNOWN'
        END AS latency_status
    FROM run
),
finalized AS (
    SELECT
        classified.*,
        CASE
            WHEN execution_status IN (
                'FILLED',
                'PARTIALLY_FILLED'
            ) THEN 'SUCCESS'
            WHEN execution_status = 'ACCEPTED_OPEN'
             AND latency_status = 'TOO_SLOW'
                THEN 'LATENCY_MISS'
            WHEN execution_status IN ('REJECTED', 'ERROR')
                THEN 'ERROR'
            WHEN source_status IN (
                'NO_MATCH',
                'QUARANTINED',
                'ERROR'
            ) THEN 'ERROR'
            WHEN schedule_state = 'EXPIRED'
             AND claim_id IS NULL THEN 'MISSED_EXECUTION'
            ELSE 'PENDING'
        END AS overall_result
    FROM classified
)
INSERT INTO resolution_run_journal (
    journal_key,
    scope_id,
    profile_key,
    schedule_key,
    source_kind,
    source_provider,
    source_event_ref,
    fact_ref,
    execution_claim_ref,
    live_block,
    block_id,
    selected_outcome,
    direction_status,
    execution_status,
    latency_status,
    overall_result,
    desired_price,
    effective_price,
    quantity,
    matched_quantity,
    source_published_at,
    source_detected_at,
    claim_created_at,
    exchange_completed_at,
    first_order_observed_at,
    last_order_observed_at,
    source_latency_ms,
    decision_latency_ms,
    exchange_latency_ms,
    source_url,
    market_url,
    error_stage,
    error_code,
    errors,
    classification_reason,
    details,
    finalized_at
)
SELECT
    scope_id || ':' || to_char(
        activate_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD'
    ),
    scope_id,
    profile_key,
    schedule_key,
    'earnings',
    coalesce(fact_provider, source_provider),
    CASE
        WHEN source_event_id IS NULL THEN NULL
        ELSE 'earnings_source_events:' || source_event_id
    END,
    CASE
        WHEN fact_id IS NULL THEN NULL
        ELSE 'earnings_fact_candidates:' || fact_id
    END,
    CASE
        WHEN claim_id IS NULL THEN NULL
        ELSE 'resolution_execution_claims:' || claim_id
    END,
    live_block,
    block_id,
    selected_outcome,
    'UNKNOWN',
    execution_status,
    latency_status,
    overall_result,
    coalesce(
        claim_desired_price,
        CASE selected_outcome
            WHEN 'YES' THEN yes_desired_price
            WHEN 'NO' THEN no_desired_price
            ELSE NULL
        END
    ),
    coalesce(current_effective_price, claim_effective_price),
    coalesce(claim_quantity, profile_quantity),
    CASE
        WHEN claim_id IS NULL THEN NULL
        ELSE matched_quantity
    END,
    coalesce(published_at, filed_at),
    coalesce(detected_at, received_at),
    claim_created_at,
    claim_completed_at,
    first_opened_at,
    last_opened_at,
    CASE
        WHEN coalesce(detected_at, received_at) IS NULL
          OR coalesce(published_at, filed_at) IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    coalesce(detected_at, received_at)
                    - coalesce(published_at, filed_at)
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN claim_created_at IS NULL OR detected_at IS NULL
            THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    claim_created_at - detected_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN claim_completed_at IS NULL
          OR claim_created_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    claim_completed_at - claim_created_at
                )) * 1000
            )::bigint
        )
    END,
    source_url,
    market_url,
    CASE
        WHEN source_status IN (
            'NO_MATCH',
            'QUARANTINED',
            'ERROR'
        ) THEN 'source'
        WHEN claim_status IN ('REJECTED', 'ERROR') THEN 'execution'
        ELSE NULL
    END,
    CASE
        WHEN source_status IN (
            'NO_MATCH',
            'QUARANTINED',
            'ERROR'
        ) THEN 'source_' || lower(source_status)
        WHEN claim_status IN ('REJECTED', 'ERROR')
            THEN lower(claim_status)
        ELSE NULL
    END,
    CASE
        WHEN source_status IN (
            'NO_MATCH',
            'QUARANTINED',
            'ERROR'
        ) THEN jsonb_build_array(
            jsonb_build_object(
                'stage', 'source',
                'code', 'source_' || lower(source_status)
            )
        )
        ELSE '[]'::jsonb
    END,
    CASE
        WHEN overall_result = 'SUCCESS'
            THEN 'automatic_fill_observed'
        WHEN overall_result = 'LATENCY_MISS'
            THEN 'automatic_open_order_at_high_effective_price'
        WHEN overall_result = 'MISSED_EXECUTION'
            THEN 'automatic_expired_without_execution'
        WHEN overall_result = 'ERROR'
            THEN 'automatic_source_or_execution_error'
        ELSE 'automatic_pending_classification'
    END,
    jsonb_build_object(
        'fact_value', fact_value,
        'strike', strike,
        'comparison_op', comparison_op,
        'auto_reconciled', true
    ),
    CASE
        WHEN overall_result IN (
            'SUCCESS',
            'MISSED_EXECUTION',
            'ERROR'
        ) THEN now()
        ELSE NULL
    END
FROM finalized
ON CONFLICT (journal_key) DO UPDATE
SET
    source_provider = EXCLUDED.source_provider,
    source_event_ref = EXCLUDED.source_event_ref,
    fact_ref = EXCLUDED.fact_ref,
    execution_claim_ref = EXCLUDED.execution_claim_ref,
    selected_outcome = EXCLUDED.selected_outcome,
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    desired_price = EXCLUDED.desired_price,
    effective_price = EXCLUDED.effective_price,
    quantity = EXCLUDED.quantity,
    matched_quantity = EXCLUDED.matched_quantity,
    source_published_at = EXCLUDED.source_published_at,
    source_detected_at = EXCLUDED.source_detected_at,
    claim_created_at = EXCLUDED.claim_created_at,
    exchange_completed_at = EXCLUDED.exchange_completed_at,
    first_order_observed_at = EXCLUDED.first_order_observed_at,
    last_order_observed_at = EXCLUDED.last_order_observed_at,
    source_latency_ms = EXCLUDED.source_latency_ms,
    decision_latency_ms = EXCLUDED.decision_latency_ms,
    exchange_latency_ms = EXCLUDED.exchange_latency_ms,
    source_url = EXCLUDED.source_url,
    market_url = EXCLUDED.market_url,
    error_stage = EXCLUDED.error_stage,
    error_code = EXCLUDED.error_code,
    errors = EXCLUDED.errors,
    classification_reason = EXCLUDED.classification_reason,
    details = EXCLUDED.details,
    finalized_at = EXCLUDED.finalized_at,
    updated_at = now()
WHERE coalesce(
    resolution_run_journal.details ->> 'reviewed_after_block',
    'false'
) <> 'true'
  AND ROW(
      resolution_run_journal.source_provider,
      resolution_run_journal.source_event_ref,
      resolution_run_journal.fact_ref,
      resolution_run_journal.execution_claim_ref,
      resolution_run_journal.selected_outcome,
      resolution_run_journal.execution_status,
      resolution_run_journal.latency_status,
      resolution_run_journal.overall_result,
      resolution_run_journal.desired_price,
      resolution_run_journal.effective_price,
      resolution_run_journal.quantity,
      resolution_run_journal.matched_quantity,
      resolution_run_journal.source_published_at,
      resolution_run_journal.source_detected_at,
      resolution_run_journal.claim_created_at,
      resolution_run_journal.exchange_completed_at,
      resolution_run_journal.first_order_observed_at,
      resolution_run_journal.last_order_observed_at,
      resolution_run_journal.source_url,
      resolution_run_journal.error_stage,
      resolution_run_journal.error_code
  ) IS DISTINCT FROM ROW(
      EXCLUDED.source_provider,
      EXCLUDED.source_event_ref,
      EXCLUDED.fact_ref,
      EXCLUDED.execution_claim_ref,
      EXCLUDED.selected_outcome,
      EXCLUDED.execution_status,
      EXCLUDED.latency_status,
      EXCLUDED.overall_result,
      EXCLUDED.desired_price,
      EXCLUDED.effective_price,
      EXCLUDED.quantity,
      EXCLUDED.matched_quantity,
      EXCLUDED.source_published_at,
      EXCLUDED.source_detected_at,
      EXCLUDED.claim_created_at,
      EXCLUDED.exchange_completed_at,
      EXCLUDED.first_order_observed_at,
      EXCLUDED.last_order_observed_at,
      EXCLUDED.source_url,
      EXCLUDED.error_stage,
      EXCLUDED.error_code
  )
RETURNING id
""".strip()

_RECORD_TRANSITIONS_SQL = """
INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    latency_ms,
    error_code,
    details,
    occurred_at
)
SELECT
    'auto:' || journal.journal_key || ':'
        || journal.overall_result || ':'
        || journal.execution_status,
    journal.id,
    'AUTOMATIC_RECONCILIATION',
    coalesce(journal.error_stage, 'execution'),
    journal.overall_result,
    journal.source_latency_ms,
    journal.error_code,
    jsonb_build_object(
        'execution_status', journal.execution_status,
        'latency_status', journal.latency_status,
        'direction_status', journal.direction_status
    ),
    journal.updated_at
FROM resolution_run_journal AS journal
WHERE journal.details ->> 'auto_reconciled' = 'true'
  AND journal.updated_at >= now() - interval '10 seconds'
ON CONFLICT (event_key) DO NOTHING
""".strip()


class ResolutionRunJournalStoreError(RuntimeError):
    """Sanitized persistence failure for the resolution run journal."""


class SqlAlchemyResolutionRunJournalStore:
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
        self._ready = False

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
        except Exception as exc:
            raise ResolutionRunJournalStoreError(
                "Failed to verify resolution run journal schema: "
                f"{type(exc).__name__}"
            ) from None
        if not all(bool(value) for value in row.values()):
            raise ResolutionRunJournalStoreError(
                "Resolution run journal schema is not ready"
            )
        self._ready = True

    def reconcile_earnings(self) -> int:
        if not self._ready:
            self.ensure_ready()
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_RECONCILE_EARNINGS_SQL)
                ).mappings().all()
                session.execute(text_factory(_RECORD_TRANSITIONS_SQL))
                session.commit()
        except Exception as exc:
            raise ResolutionRunJournalStoreError(
                "Failed to reconcile earnings run journal: "
                f"{type(exc).__name__}"
            ) from None
        return len(rows)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise ResolutionRunJournalStoreError(
                    "Resolution run journal database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise ResolutionRunJournalStoreError(
                    "Resolution run journal requires SQLAlchemy "
                    "and a PostgreSQL driver"
                ) from None
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
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise ResolutionRunJournalStoreError(
                    "Resolution run journal requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url
