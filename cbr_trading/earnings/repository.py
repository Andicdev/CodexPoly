from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Sequence

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsProvider,
    EarningsSourceTiming,
    EpsBasis,
    SourceAuthority,
)
from cbr_trading.secret_guard import redact_sensitive_text


_MIGRATION_PATHS = (
    (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "004_add_earnings_source_tables.sql"
    ),
    (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "016_add_earnings_source_telemetry.sql"
    ),
    (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "018_add_observation_only_earnings_facts.sql"
    ),
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('earnings_market_rules') IS NOT NULL AS rules_table,
    to_regclass('earnings_source_events') IS NOT NULL AS events_table,
    to_regclass('earnings_fact_candidates') IS NOT NULL AS facts_table,
    to_regclass(
        'earnings_source_processing_telemetry'
    ) IS NOT NULL AS processing_telemetry_table,
    to_regclass(
        'earnings_source_transport_observations'
    ) IS NOT NULL AS transport_observations_table,
    to_regclass(
        'earnings_source_race_observations'
    ) IS NOT NULL AS source_race_view,
    (
        SELECT count(*) = 23
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_market_rules'
    ) AS rules_columns,
    (
        SELECT count(*) = 22
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_source_events'
    ) AS events_columns,
    (
        SELECT count(*) = 25
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_fact_candidates'
    ) AS facts_columns,
    (
        SELECT count(*) = 11
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'earnings_source_processing_telemetry'
    ) AS processing_telemetry_columns,
    (
        SELECT count(*) = 8
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'earnings_source_transport_observations'
    ) AS transport_observations_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_market_rules_scope_id'
        )
          AND indisunique
    ) AS rules_scope_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_source_events_key'
        )
          AND indisunique
    ) AS events_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_fact_candidates_key'
        )
          AND indisunique
    ) AS facts_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_source_transport_observations_event_transport'
        )
          AND indisunique
    ) AS transport_observations_key_index,
    EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass(
            'earnings_fact_candidates'
        )
          AND conname =
              'earnings_fact_candidates_status_check'
          AND pg_get_constraintdef(oid) LIKE '%OBSERVED%'
    ) AS observed_fact_status,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ix_earnings_source_processing_telemetry_transport'
        )
    ) AS processing_telemetry_transport_index
""".strip()

_UPSERT_RULE_SQL = """
INSERT INTO earnings_market_rules (
    rule_key,
    scope_id,
    ticker,
    cik,
    fiscal_year,
    fiscal_quarter,
    period_end,
    estimated_release_at,
    metric_kind,
    primary_basis,
    fallback_basis,
    comparison_op,
    strike,
    rounding_places,
    currency,
    market_slug,
    condition_id,
    source_policy,
    fallback_policy,
    status
)
VALUES (
    :rule_key,
    :scope_id,
    :ticker,
    :cik,
    :fiscal_year,
    :fiscal_quarter,
    :period_end,
    :estimated_release_at,
    :metric_kind,
    :primary_basis,
    :fallback_basis,
    :comparison_op,
    :strike,
    :rounding_places,
    :currency,
    :market_slug,
    :condition_id,
    CAST(:source_policy AS jsonb),
    CAST(:fallback_policy AS jsonb),
    :status
)
ON CONFLICT (rule_key) DO UPDATE
SET
    scope_id = EXCLUDED.scope_id,
    ticker = EXCLUDED.ticker,
    cik = EXCLUDED.cik,
    fiscal_year = EXCLUDED.fiscal_year,
    fiscal_quarter = EXCLUDED.fiscal_quarter,
    period_end = EXCLUDED.period_end,
    estimated_release_at = EXCLUDED.estimated_release_at,
    metric_kind = EXCLUDED.metric_kind,
    primary_basis = EXCLUDED.primary_basis,
    fallback_basis = EXCLUDED.fallback_basis,
    comparison_op = EXCLUDED.comparison_op,
    strike = EXCLUDED.strike,
    rounding_places = EXCLUDED.rounding_places,
    currency = EXCLUDED.currency,
    market_slug = EXCLUDED.market_slug,
    condition_id = EXCLUDED.condition_id,
    source_policy = EXCLUDED.source_policy,
    fallback_policy = EXCLUDED.fallback_policy,
    updated_at = now()
RETURNING id
""".strip()

_INSERT_EVENT_SQL = """
WITH inserted_event AS (
    INSERT INTO earnings_source_events (
        idempotency_key,
        rule_id,
        scope_id,
        provider,
        provider_event_id,
        ticker,
        cik,
        form_type,
        items,
        document_type,
        source_url,
        filing_url,
        filed_at,
        received_at,
        authority,
        transport_fingerprint,
        metadata
    )
    SELECT
        :idempotency_key,
        rule.id,
        :scope_id,
        :provider,
        :provider_event_id,
        :ticker,
        :cik,
        :form_type,
        CAST(:items AS jsonb),
        :document_type,
        :source_url,
        :filing_url,
        :filed_at,
        :received_at,
        :authority,
        :transport_fingerprint,
        CAST(:metadata AS jsonb)
    FROM earnings_market_rules AS rule
    WHERE rule.scope_id = :scope_id
    ON CONFLICT DO NOTHING
    RETURNING id
),
inserted_processing_telemetry AS (
    INSERT INTO earnings_source_processing_telemetry (
        source_event_id,
        source_transport,
        transport_observed_at
    )
    SELECT
        id,
        :source_transport,
        :transport_observed_at
    FROM inserted_event
    ON CONFLICT (source_event_id) DO NOTHING
    RETURNING source_event_id
),
inserted_transport_observation AS (
    INSERT INTO earnings_source_transport_observations (
        source_event_id,
        transport,
        first_observed_at,
        last_observed_at
    )
    SELECT
        id,
        :source_transport,
        :transport_observed_at,
        :transport_observed_at
    FROM inserted_event
    ON CONFLICT (source_event_id, transport) DO NOTHING
    RETURNING source_event_id
)
SELECT inserted_event.id
FROM inserted_event
JOIN inserted_processing_telemetry
  ON inserted_processing_telemetry.source_event_id =
      inserted_event.id
JOIN inserted_transport_observation
  ON inserted_transport_observation.source_event_id =
      inserted_event.id
""".strip()

_SELECT_EVENT_SQL = """
SELECT id, status
FROM earnings_source_events
WHERE idempotency_key = :idempotency_key
LIMIT 1
""".strip()

_UPSERT_DUPLICATE_TELEMETRY_SQL = """
WITH inserted_processing_telemetry AS (
    INSERT INTO earnings_source_processing_telemetry (
        source_event_id,
        source_transport,
        transport_observed_at
    )
    VALUES (
        :source_event_id,
        :source_transport,
        :transport_observed_at
    )
    ON CONFLICT (source_event_id) DO NOTHING
    RETURNING source_event_id
)
INSERT INTO earnings_source_transport_observations (
    source_event_id,
    transport,
    first_observed_at,
    last_observed_at
)
VALUES (
    :source_event_id,
    :source_transport,
    :transport_observed_at,
    :transport_observed_at
)
ON CONFLICT (source_event_id, transport) DO UPDATE
SET
    first_observed_at = least(
        earnings_source_transport_observations.first_observed_at,
        EXCLUDED.first_observed_at
    ),
    last_observed_at = greatest(
        earnings_source_transport_observations.last_observed_at,
        EXCLUDED.last_observed_at
    ),
    observation_count =
        earnings_source_transport_observations.observation_count + 1,
    updated_at = now()
""".strip()

_UPDATE_EVENT_STATUS_SQL = """
WITH updated_event AS (
    UPDATE earnings_source_events
    SET
        status = :status,
        error = :error,
        updated_at = now()
    WHERE id = :event_id
    RETURNING id
)
INSERT INTO earnings_source_processing_telemetry (
    source_event_id,
    source_transport,
    transport_observed_at,
    document_fetch_started_at,
    document_fetch_completed_at,
    document_fetch_route,
    parse_started_at,
    parse_completed_at,
    fact_persisted_at
)
SELECT
    id,
    coalesce(:source_transport, 'legacy_unknown'),
    coalesce(:transport_observed_at, now()),
    :document_fetch_started_at,
    :document_fetch_completed_at,
    :document_fetch_route,
    :parse_started_at,
    :parse_completed_at,
    :fact_persisted_at
FROM updated_event
ON CONFLICT (source_event_id) DO UPDATE
SET
    source_transport = coalesce(
        :source_transport,
        earnings_source_processing_telemetry.source_transport
    ),
    transport_observed_at = coalesce(
        :transport_observed_at,
        earnings_source_processing_telemetry.transport_observed_at
    ),
    document_fetch_started_at = coalesce(
        :document_fetch_started_at,
        earnings_source_processing_telemetry.document_fetch_started_at
    ),
    document_fetch_completed_at = coalesce(
        :document_fetch_completed_at,
        earnings_source_processing_telemetry.document_fetch_completed_at
    ),
    document_fetch_route = coalesce(
        :document_fetch_route,
        earnings_source_processing_telemetry.document_fetch_route
    ),
    parse_started_at = coalesce(
        :parse_started_at,
        earnings_source_processing_telemetry.parse_started_at
    ),
    parse_completed_at = coalesce(
        :parse_completed_at,
        earnings_source_processing_telemetry.parse_completed_at
    ),
    fact_persisted_at = coalesce(
        :fact_persisted_at,
        earnings_source_processing_telemetry.fact_persisted_at
    ),
    updated_at = now()
RETURNING source_event_id AS id
""".strip()

_INSERT_FACT_SQL = """
INSERT INTO earnings_fact_candidates (
    idempotency_key,
    source_event_id,
    scope_id,
    ticker,
    cik,
    period_end,
    metric_kind,
    basis,
    currency,
    raw_value,
    value,
    authority,
    provider,
    parser_name,
    parser_version,
    confidence,
    document_fingerprint,
    evidence,
    status,
    reason,
    published_at,
    detected_at
)
VALUES (
    :idempotency_key,
    :source_event_id,
    :scope_id,
    :ticker,
    :cik,
    :period_end,
    :metric_kind,
    :basis,
    :currency,
    :raw_value,
    :value,
    :authority,
    :provider,
    :parser_name,
    :parser_version,
    :confidence,
    :document_fingerprint,
    CAST(:evidence AS jsonb),
    :status,
    :reason,
    :published_at,
    :detected_at
)
ON CONFLICT DO NOTHING
RETURNING id
""".strip()

_SELECT_FACT_SQL = """
SELECT id
FROM earnings_fact_candidates
WHERE idempotency_key = :idempotency_key
LIMIT 1
""".strip()

_LOAD_VALIDATED_FACTS_SQL = """
SELECT
    fact.scope_id,
    fact.provider,
    event.provider_event_id,
    fact.ticker,
    fact.cik,
    fact.period_end,
    fact.metric_kind,
    fact.basis,
    fact.currency,
    fact.raw_value,
    fact.value,
    fact.authority,
    event.source_url,
    event.filing_url,
    fact.published_at,
    fact.detected_at,
    fact.parser_name,
    fact.parser_version,
    fact.confidence,
    fact.document_fingerprint,
    fact.evidence
FROM earnings_fact_candidates AS fact
JOIN earnings_source_events AS event
  ON event.id = fact.source_event_id
WHERE fact.status = 'VALIDATED'
  AND (
      CAST(:scope_id AS text) IS NULL
      OR fact.scope_id = CAST(:scope_id AS text)
  )
ORDER BY fact.detected_at, fact.id
""".strip()

_LOAD_ACTIVE_RULES_SQL = """
SELECT
    rule_key,
    scope_id,
    ticker,
    cik,
    fiscal_year,
    fiscal_quarter,
    period_end,
    estimated_release_at,
    metric_kind,
    primary_basis,
    fallback_basis,
    comparison_op,
    strike,
    rounding_places,
    currency,
    market_slug,
    condition_id,
    source_policy,
    fallback_policy
FROM earnings_market_rules
WHERE status IN ('SHADOW', 'WATCHING')
ORDER BY estimated_release_at, id
""".strip()

_EVENT_STATUSES = frozenset(
    {
        "RECEIVED",
        "FETCHED",
        "PARSED",
        "NO_MATCH",
        "QUARANTINED",
        "ERROR",
    }
)

_FACT_STATUSES = frozenset({"VALIDATED", "OBSERVED"})


class EarningsStoreError(RuntimeError):
    """Sanitized failure in additive earnings shadow persistence."""


@dataclass(frozen=True)
class StoredEarningsRecord:
    row_id: int
    created: bool
    status: str | None = None


class SqlAlchemyEarningsStore:
    """Explicit migration and idempotent persistence for shadow earnings data."""

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
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                for migration_path in _MIGRATION_PATHS:
                    session.execute(
                        text_factory(
                            migration_path.read_text(encoding="utf-8")
                        )
                    )
                session.commit()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to apply additive earnings migration: "
                f"{type(exc).__name__}"
            ) from None

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to verify earnings schema: "
                f"{type(exc).__name__}"
            ) from None
        expected = (
            "rules_table",
            "events_table",
            "facts_table",
            "processing_telemetry_table",
            "transport_observations_table",
            "source_race_view",
            "rules_columns",
            "events_columns",
            "facts_columns",
            "processing_telemetry_columns",
            "transport_observations_columns",
            "rules_scope_index",
            "events_key_index",
            "facts_key_index",
            "transport_observations_key_index",
            "observed_fact_status",
            "processing_telemetry_transport_index",
        )
        if not all(bool(row.get(name)) for name in expected):
            raise EarningsStoreError(
                "Earnings shadow source tables are not ready"
            )

    def save_shadow_rule(
        self,
        rule: EarningsMarketRule,
    ) -> int:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_UPSERT_RULE_SQL),
                    _rule_params(rule),
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to save shadow earnings rule: "
                f"{type(exc).__name__}"
            ) from None
        return int(row["id"])

    def record_source_event(
        self,
        candidate: EarningsDocumentCandidate,
    ) -> StoredEarningsRecord:
        idempotency_key = _event_key(candidate)
        params = _event_params(candidate, idempotency_key)
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_EVENT_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is not None:
                    event_id = int(inserted["id"])
                    session.commit()
                    return StoredEarningsRecord(
                        row_id=event_id,
                        created=True,
                        status="RECEIVED",
                    )
                existing = session.execute(
                    text_factory(_SELECT_EVENT_SQL),
                    {"idempotency_key": idempotency_key},
                ).mappings().one_or_none()
                if existing is None:
                    session.rollback()
                else:
                    event_id = int(existing["id"])
                    session.execute(
                        text_factory(
                            _UPSERT_DUPLICATE_TELEMETRY_SQL
                        ),
                        _transport_observation_params(
                            event_id=event_id,
                            candidate=candidate,
                        ),
                    )
                    session.commit()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to record earnings source event: "
                f"{type(exc).__name__}"
            ) from None
        if existing is None:
            raise EarningsStoreError(
                "Earnings source event has no matching shadow rule"
            )
        return StoredEarningsRecord(
            row_id=int(existing["id"]),
            created=False,
            status=str(existing["status"]),
        )

    def update_source_event_status(
        self,
        event_id: int,
        *,
        status: str,
        error: str | None = None,
        timing: EarningsSourceTiming | None = None,
    ) -> None:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in _EVENT_STATUSES:
            raise ValueError("unsupported earnings source event status")
        safe_error = (
            redact_sensitive_text(error, max_length=240)
            if error is not None
            else None
        )
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                updated = session.execute(
                    text_factory(_UPDATE_EVENT_STATUS_SQL),
                    {
                        "event_id": int(event_id),
                        "status": normalized_status,
                        "error": safe_error,
                        **_timing_params(timing),
                    },
                ).mappings().one_or_none()
                if updated is None:
                    session.rollback()
                    raise EarningsStoreError(
                        "Earnings source event does not exist"
                    )
                session.commit()
        except EarningsStoreError:
            raise
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to update earnings source event: "
                f"{type(exc).__name__}"
            ) from None

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate: EarningsFactCandidate,
        reason: str,
        status: str = "VALIDATED",
    ) -> StoredEarningsRecord:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in _FACT_STATUSES:
            raise ValueError(
                "unsupported earnings fact persistence status"
            )
        idempotency_key = _fact_key(candidate)
        params = _fact_params(
            source_event_id=source_event_id,
            candidate=candidate,
            reason=reason,
            idempotency_key=idempotency_key,
            status=normalized_status,
        )
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_FACT_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is not None:
                    session.commit()
                    return StoredEarningsRecord(
                        row_id=int(inserted["id"]),
                        created=True,
                    )
                existing = session.execute(
                    text_factory(_SELECT_FACT_SQL),
                    {"idempotency_key": idempotency_key},
                ).mappings().one_or_none()
                session.rollback()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to record earnings fact candidate: "
                f"{type(exc).__name__}"
            ) from None
        if existing is None:
            raise EarningsStoreError(
                "Earnings fact candidate was not persisted"
            )
        return StoredEarningsRecord(
            row_id=int(existing["id"]),
            created=False,
        )

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> tuple[EarningsFactCandidate, ...]:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_LOAD_VALIDATED_FACTS_SQL),
                    {
                        "scope_id": (
                            str(scope_id or "").strip()
                            or None
                        )
                    },
                ).mappings().all()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to load earnings fact candidates: "
                f"{type(exc).__name__}"
            ) from None
        return tuple(_fact_from_row(row) for row in rows)

    def load_active_rules(self) -> tuple[EarningsMarketRule, ...]:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_LOAD_ACTIVE_RULES_SQL)
                ).mappings().all()
        except Exception as exc:
            raise EarningsStoreError(
                "Failed to load active earnings rules: "
                f"{type(exc).__name__}"
            ) from None
        return tuple(_rule_from_row(row) for row in rows)

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
                raise EarningsStoreError(
                    "Earnings database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise EarningsStoreError(
                    "Earnings persistence requires SQLAlchemy "
                    "and a PostgreSQL driver"
                ) from None
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
                raise EarningsStoreError(
                    "Failed to initialize earnings persistence: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise EarningsStoreError(
                    "Earnings persistence requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _rule_params(rule: EarningsMarketRule) -> dict[str, Any]:
    return {
        "rule_key": rule.rule_key,
        "scope_id": rule.scope_id,
        "ticker": rule.ticker,
        "cik": rule.cik,
        "fiscal_year": rule.fiscal_year,
        "fiscal_quarter": rule.fiscal_quarter,
        "period_end": rule.period_end,
        "estimated_release_at": rule.estimated_release_at,
        "metric_kind": rule.metric.value,
        "primary_basis": rule.primary_basis.value,
        "fallback_basis": rule.fallback_basis.value,
        "comparison_op": rule.comparison_op,
        "strike": rule.strike,
        "rounding_places": rule.rounding_places,
        "currency": rule.currency,
        "market_slug": rule.market_slug,
        "condition_id": rule.condition_id,
        "source_policy": _json_dumps(rule.source_policy),
        "fallback_policy": _json_dumps(rule.fallback_policy),
        "status": "SHADOW",
    }


def _rule_from_row(row: Any) -> EarningsMarketRule:
    return EarningsMarketRule(
        rule_key=str(row["rule_key"]),
        scope_id=str(row["scope_id"]),
        ticker=str(row["ticker"]),
        cik=str(row["cik"]),
        fiscal_year=int(row["fiscal_year"]),
        fiscal_quarter=int(row["fiscal_quarter"]),
        period_end=row["period_end"],
        estimated_release_at=row["estimated_release_at"],
        metric=EarningsMetric(str(row["metric_kind"])),
        primary_basis=EpsBasis(str(row["primary_basis"])),
        fallback_basis=EpsBasis(str(row["fallback_basis"])),
        comparison_op=str(row["comparison_op"]),
        strike=row["strike"],
        rounding_places=int(row["rounding_places"]),
        currency=str(row["currency"]),
        market_slug=row.get("market_slug"),
        condition_id=row.get("condition_id"),
        source_policy=_json_mapping(row.get("source_policy")),
        fallback_policy=_json_mapping(row.get("fallback_policy")),
    )


def _event_params(
    candidate: EarningsDocumentCandidate,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "idempotency_key": idempotency_key,
        "scope_id": candidate.scope_id,
        "provider": candidate.provider.value,
        "provider_event_id": candidate.provider_event_id,
        "ticker": candidate.ticker,
        "cik": candidate.cik,
        "form_type": candidate.form_type,
        "items": _json_dumps(candidate.items),
        "document_type": candidate.document_type,
        "source_url": candidate.source_url,
        "filing_url": candidate.filing_url,
        "filed_at": candidate.filed_at,
        "received_at": candidate.received_at,
        "authority": candidate.authority.value,
        "transport_fingerprint": candidate.transport_fingerprint,
        "source_transport": candidate.transport.value,
        "transport_observed_at": candidate.received_at,
        "metadata": _json_dumps(candidate.metadata),
    }


def _transport_observation_params(
    *,
    event_id: int,
    candidate: EarningsDocumentCandidate,
) -> dict[str, Any]:
    return {
        "source_event_id": int(event_id),
        "source_transport": candidate.transport.value,
        "transport_observed_at": candidate.received_at,
    }


def _timing_params(
    timing: EarningsSourceTiming | None,
) -> dict[str, Any]:
    if timing is None:
        return {
            "source_transport": None,
            "transport_observed_at": None,
            "document_fetch_started_at": None,
            "document_fetch_completed_at": None,
            "document_fetch_route": None,
            "parse_started_at": None,
            "parse_completed_at": None,
            "fact_persisted_at": None,
        }
    return {
        "source_transport": timing.transport.value,
        "transport_observed_at": timing.transport_observed_at,
        "document_fetch_started_at": timing.document_fetch_started_at,
        "document_fetch_completed_at": (
            timing.document_fetch_completed_at
        ),
        "document_fetch_route": timing.document_fetch_route,
        "parse_started_at": timing.parse_started_at,
        "parse_completed_at": timing.parse_completed_at,
        "fact_persisted_at": timing.fact_persisted_at,
    }


def _fact_params(
    *,
    source_event_id: int,
    candidate: EarningsFactCandidate,
    reason: str,
    idempotency_key: str,
    status: str,
) -> dict[str, Any]:
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("reason is required")
    evidence = {
        "source_url": candidate.source_url,
        "filing_url": candidate.filing_url,
        "title": candidate.evidence_title,
        "excerpt": candidate.excerpt,
        "attributes": dict(candidate.attributes),
    }
    return {
        "idempotency_key": idempotency_key,
        "source_event_id": int(source_event_id),
        "scope_id": candidate.scope_id,
        "ticker": candidate.ticker,
        "cik": candidate.cik,
        "period_end": candidate.period_end,
        "metric_kind": candidate.metric.value,
        "basis": candidate.basis.value,
        "currency": candidate.currency,
        "raw_value": candidate.raw_value,
        "value": candidate.value,
        "authority": candidate.authority.value,
        "provider": candidate.provider.value,
        "parser_name": candidate.parser_name,
        "parser_version": candidate.parser_version,
        "confidence": candidate.confidence,
        "document_fingerprint": candidate.document_fingerprint,
        "evidence": _json_dumps(evidence),
        "status": status,
        "reason": normalized_reason,
        "published_at": candidate.published_at,
        "detected_at": candidate.detected_at,
    }


def _fact_from_row(row: Any) -> EarningsFactCandidate:
    evidence = dict(row.get("evidence") or {})
    return EarningsFactCandidate(
        scope_id=str(row["scope_id"]),
        provider=EarningsProvider(str(row["provider"])),
        provider_event_id=str(row["provider_event_id"]),
        ticker=str(row["ticker"]),
        cik=str(row["cik"]),
        period_end=row["period_end"],
        metric=EarningsMetric(str(row["metric_kind"])),
        basis=EpsBasis(str(row["basis"])),
        currency=str(row["currency"]),
        raw_value=row["raw_value"],
        value=row["value"],
        authority=SourceAuthority(str(row["authority"])),
        source_url=str(row["source_url"]),
        filing_url=str(row["filing_url"]),
        published_at=row["published_at"],
        detected_at=row["detected_at"],
        parser_name=str(row["parser_name"]),
        parser_version=str(row["parser_version"]),
        confidence=row["confidence"],
        document_fingerprint=str(row["document_fingerprint"]),
        evidence_title=evidence.get("title"),
        excerpt=evidence.get("excerpt"),
        attributes=evidence.get("attributes") or {},
    )


def _event_key(candidate: EarningsDocumentCandidate) -> str:
    return "earnings-event:v1:" + hashlib.sha256(
        (
            f"{candidate.scope_id}|{candidate.provider.value}|"
            f"{candidate.provider_event_id}|{candidate.source_url}"
        ).encode("utf-8")
    ).hexdigest()


def _fact_key(candidate: EarningsFactCandidate) -> str:
    return "earnings-fact:v1:" + hashlib.sha256(
        (
            f"{candidate.scope_id}|{candidate.provider.value}|"
            f"{candidate.provider_event_id}|"
            f"{candidate.document_fingerprint}|"
            f"{candidate.parser_name}|{candidate.parser_version}|"
            f"{candidate.metric.value}|{candidate.basis.value}|"
            f"{candidate.value}"
        ).encode("utf-8")
    ).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        decoded = json.loads(value)
    else:
        decoded = value
    if not isinstance(decoded, dict):
        raise ValueError("earnings rule policy must be a JSON object")
    return dict(decoded)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        f"unsupported JSON value type: {type(value).__name__}"
    )


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
