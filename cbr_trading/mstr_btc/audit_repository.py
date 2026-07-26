from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from cbr_trading.mstr_btc.contracts import (
    MstrBtcAuditStatus,
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcValueDerivation,
)
from cbr_trading.secret_guard import redact_sensitive_text


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "009_add_mstr_btc_source_audit.sql"
)
_SET_READ_ONLY_SQL = "SET TRANSACTION READ ONLY"

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('mstr_btc_source_events') IS NOT NULL AS events_table,
    to_regclass('mstr_btc_fact_candidates') IS NOT NULL AS facts_table,
    to_regclass('mstr_btc_processing_results') IS NOT NULL AS results_table,
    (
        SELECT count(*) = 15
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mstr_btc_source_events'
    ) AS events_columns,
    (
        SELECT count(*) = 25
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mstr_btc_fact_candidates'
    ) AS facts_columns,
    (
        SELECT count(*) = 8
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mstr_btc_processing_results'
    ) AS results_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_mstr_btc_source_events_key'
        )
          AND indisunique
    ) AS events_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_mstr_btc_fact_candidates_key'
        )
          AND indisunique
    ) AS facts_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_mstr_btc_processing_results_terminal'
        )
          AND indisunique
    ) AS terminal_index,
    (
        SELECT count(*) = 3
        FROM pg_trigger
        WHERE tgrelid IN (
            to_regclass('mstr_btc_source_events'),
            to_regclass('mstr_btc_fact_candidates'),
            to_regclass('mstr_btc_processing_results')
        )
          AND tgname IN (
            'trg_mstr_btc_source_events_append_only',
            'trg_mstr_btc_fact_candidates_append_only',
            'trg_mstr_btc_processing_results_append_only'
        )
          AND NOT tgisinternal
    ) AS append_only_triggers
""".strip()

_INSERT_EVENT_SQL = """
INSERT INTO mstr_btc_source_events (
    idempotency_key,
    scope_id,
    provider,
    provider_event_id,
    ticker,
    cik,
    form_type,
    source_url,
    filing_url,
    filed_at,
    received_at,
    transport_fingerprint,
    metadata
)
VALUES (
    :idempotency_key,
    :scope_id,
    :provider,
    :provider_event_id,
    :ticker,
    :cik,
    :form_type,
    :source_url,
    :filing_url,
    :filed_at,
    :received_at,
    :transport_fingerprint,
    CAST(:metadata AS jsonb)
)
ON CONFLICT DO NOTHING
RETURNING id
""".strip()

_SELECT_EVENT_SQL = """
SELECT id
FROM mstr_btc_source_events
WHERE idempotency_key = :idempotency_key
LIMIT 1
""".strip()

_SELECT_TERMINAL_RESULT_SQL = """
SELECT
    id,
    status,
    reason,
    baseline_state_id,
    fact_candidate_id
FROM mstr_btc_processing_results
WHERE source_event_id = :source_event_id
  AND status IN ('ACCEPTED', 'NO_MATCH', 'QUARANTINED')
ORDER BY id DESC
LIMIT 1
""".strip()

_INSERT_FACT_SQL = """
INSERT INTO mstr_btc_fact_candidates (
    idempotency_key,
    source_event_id,
    scope_id,
    provider,
    provider_event_id,
    baseline_state_id,
    holdings_before_btc,
    holdings_after_btc,
    net_change_btc,
    acquired_btc,
    sold_btc,
    acquired_derivation,
    sold_derivation,
    holdings_crosscheck_difference_btc,
    published_at,
    detected_at,
    parser_name,
    parser_version,
    document_fingerprint,
    evidence,
    attributes,
    reason
)
VALUES (
    :idempotency_key,
    :source_event_id,
    :scope_id,
    :provider,
    :provider_event_id,
    :baseline_state_id,
    :holdings_before_btc,
    :holdings_after_btc,
    :net_change_btc,
    :acquired_btc,
    :sold_btc,
    :acquired_derivation,
    :sold_derivation,
    :holdings_crosscheck_difference_btc,
    :published_at,
    :detected_at,
    :parser_name,
    :parser_version,
    :document_fingerprint,
    CAST(:evidence AS jsonb),
    CAST(:attributes AS jsonb),
    :reason
)
ON CONFLICT DO NOTHING
RETURNING id
""".strip()

_SELECT_FACT_SQL = """
SELECT id
FROM mstr_btc_fact_candidates
WHERE idempotency_key = :idempotency_key
LIMIT 1
""".strip()

_INSERT_RESULT_SQL = """
INSERT INTO mstr_btc_processing_results (
    idempotency_key,
    source_event_id,
    status,
    reason,
    baseline_state_id,
    fact_candidate_id
)
VALUES (
    :idempotency_key,
    :source_event_id,
    :status,
    :reason,
    :baseline_state_id,
    :fact_candidate_id
)
ON CONFLICT DO NOTHING
RETURNING id
""".strip()

_SELECT_RESULT_SQL = """
SELECT id
FROM mstr_btc_processing_results
WHERE idempotency_key = :idempotency_key
LIMIT 1
""".strip()

_LOAD_VALIDATED_FACTS_SQL = """
SELECT
    fact.scope_id,
    fact.provider,
    fact.provider_event_id,
    fact.baseline_state_id,
    fact.holdings_before_btc,
    fact.holdings_after_btc,
    fact.net_change_btc,
    fact.acquired_btc,
    fact.sold_btc,
    fact.acquired_derivation,
    fact.sold_derivation,
    fact.holdings_crosscheck_difference_btc,
    event.source_url,
    event.filing_url,
    fact.published_at,
    fact.detected_at,
    fact.parser_name,
    fact.parser_version,
    fact.document_fingerprint,
    fact.evidence,
    fact.attributes
FROM mstr_btc_fact_candidates AS fact
JOIN mstr_btc_source_events AS event
  ON event.id = fact.source_event_id
WHERE fact.validation_status = 'VALIDATED'
  AND (
      CAST(:scope_id AS text) IS NULL
      OR fact.scope_id = CAST(:scope_id AS text)
  )
ORDER BY fact.detected_at, fact.id
""".strip()


class MstrBtcAuditStoreError(RuntimeError):
    """Sanitized failure in append-only MSTR source audit persistence."""


@dataclass(frozen=True)
class StoredMstrBtcAuditRecord:
    row_id: int
    created: bool


@dataclass(frozen=True)
class StoredMstrBtcTerminalResult:
    row_id: int
    status: MstrBtcAuditStatus
    reason: str
    baseline_state_id: str | None = None
    fact_candidate_id: int | None = None


class SqlAlchemyMstrBtcAuditStore:
    """Idempotent repository over immutable MSTR source audit rows."""

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
                session.execute(
                    text_factory(
                        _MIGRATION_PATH.read_text(encoding="utf-8")
                    )
                )
                session.commit()
        except Exception as exc:
            raise MstrBtcAuditStoreError(
                "Failed to apply additive MSTR source audit migration: "
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
            raise MstrBtcAuditStoreError(
                "Failed to verify MSTR source audit schema: "
                f"{type(exc).__name__}"
            ) from None
        expected = (
            "events_table",
            "facts_table",
            "results_table",
            "events_columns",
            "facts_columns",
            "results_columns",
            "events_key_index",
            "facts_key_index",
            "terminal_index",
            "append_only_triggers",
        )
        if not all(bool(row.get(name)) for name in expected):
            raise MstrBtcAuditStoreError(
                "MSTR source audit tables are not ready"
            )

    def record_source_event(
        self,
        candidate: MstrBtcDocumentCandidate,
    ) -> StoredMstrBtcAuditRecord:
        if not isinstance(candidate, MstrBtcDocumentCandidate):
            raise TypeError(
                "candidate must be MstrBtcDocumentCandidate"
            )
        idempotency_key = _event_key(candidate)
        params = {
            "idempotency_key": idempotency_key,
            "scope_id": candidate.scope_id,
            "provider": candidate.provider.value,
            "provider_event_id": candidate.provider_event_id,
            "ticker": candidate.ticker,
            "cik": candidate.cik,
            "form_type": candidate.form_type,
            "source_url": candidate.source_url,
            "filing_url": candidate.filing_url,
            "filed_at": candidate.filed_at,
            "received_at": candidate.received_at,
            "transport_fingerprint": candidate.transport_fingerprint,
            "metadata": _json_dumps(candidate.metadata),
        }
        return self._insert_or_select(
            insert_sql=_INSERT_EVENT_SQL,
            select_sql=_SELECT_EVENT_SQL,
            params=params,
            idempotency_key=idempotency_key,
            operation="source event",
        )

    def load_terminal_result(
        self,
        *,
        source_event_id: int,
    ) -> StoredMstrBtcTerminalResult | None:
        event_id = _positive_int(source_event_id, "source_event_id")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                row = session.execute(
                    text_factory(_SELECT_TERMINAL_RESULT_SQL),
                    {"source_event_id": event_id},
                ).mappings().one_or_none()
        except Exception as exc:
            raise MstrBtcAuditStoreError(
                "Failed to load MSTR terminal result: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            return None
        return StoredMstrBtcTerminalResult(
            row_id=int(row["id"]),
            status=MstrBtcAuditStatus(str(row["status"])),
            reason=str(row["reason"]),
            baseline_state_id=(
                str(row["baseline_state_id"])
                if row.get("baseline_state_id") is not None
                else None
            ),
            fact_candidate_id=(
                int(row["fact_candidate_id"])
                if row.get("fact_candidate_id") is not None
                else None
            ),
        )

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate: MstrBtcFactCandidate,
        reason: str,
    ) -> StoredMstrBtcAuditRecord:
        event_id = _positive_int(source_event_id, "source_event_id")
        if not isinstance(candidate, MstrBtcFactCandidate):
            raise TypeError("candidate must be MstrBtcFactCandidate")
        baseline_state_id = _positive_int(
            candidate.baseline_state_id,
            "baseline_state_id",
        )
        safe_reason = _safe_reason(reason)
        idempotency_key = _fact_key(candidate)
        params = {
            "idempotency_key": idempotency_key,
            "source_event_id": event_id,
            "scope_id": candidate.scope_id,
            "provider": candidate.provider.value,
            "provider_event_id": candidate.provider_event_id,
            "baseline_state_id": baseline_state_id,
            "holdings_before_btc": candidate.holdings_before_btc,
            "holdings_after_btc": candidate.holdings_after_btc,
            "net_change_btc": candidate.net_change_btc,
            "acquired_btc": candidate.acquired_btc,
            "sold_btc": candidate.sold_btc,
            "acquired_derivation": (
                candidate.acquired_derivation.value
            ),
            "sold_derivation": candidate.sold_derivation.value,
            "holdings_crosscheck_difference_btc": (
                candidate.holdings_crosscheck_difference_btc
            ),
            "published_at": candidate.published_at,
            "detected_at": candidate.detected_at,
            "parser_name": candidate.parser_name,
            "parser_version": candidate.parser_version,
            "document_fingerprint": candidate.document_fingerprint,
            "evidence": _json_dumps(candidate.evidence_excerpts),
            "attributes": _json_dumps(candidate.attributes),
            "reason": safe_reason,
        }
        return self._insert_or_select(
            insert_sql=_INSERT_FACT_SQL,
            select_sql=_SELECT_FACT_SQL,
            params=params,
            idempotency_key=idempotency_key,
            operation="fact candidate",
        )

    def record_processing_result(
        self,
        *,
        source_event_id: int,
        status: MstrBtcAuditStatus,
        reason: str,
        baseline_state_id: str | int | None = None,
        fact_candidate_id: int | None = None,
    ) -> StoredMstrBtcAuditRecord:
        event_id = _positive_int(source_event_id, "source_event_id")
        if not isinstance(status, MstrBtcAuditStatus):
            raise TypeError("status must be MstrBtcAuditStatus")
        baseline_id = (
            _positive_int(baseline_state_id, "baseline_state_id")
            if baseline_state_id is not None
            else None
        )
        fact_id = (
            _positive_int(fact_candidate_id, "fact_candidate_id")
            if fact_candidate_id is not None
            else None
        )
        if (status is MstrBtcAuditStatus.ACCEPTED) != (
            fact_id is not None
        ):
            raise ValueError(
                "accepted result and fact_candidate_id disagree"
            )
        safe_reason = _safe_reason(reason)
        idempotency_key = _result_key(
            source_event_id=event_id,
            status=status,
            reason=safe_reason,
            baseline_state_id=baseline_id,
            fact_candidate_id=fact_id,
        )
        params = {
            "idempotency_key": idempotency_key,
            "source_event_id": event_id,
            "status": status.value,
            "reason": safe_reason,
            "baseline_state_id": baseline_id,
            "fact_candidate_id": fact_id,
        }
        return self._insert_or_select(
            insert_sql=_INSERT_RESULT_SQL,
            select_sql=_SELECT_RESULT_SQL,
            params=params,
            idempotency_key=idempotency_key,
            operation="processing result",
        )

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> tuple[MstrBtcFactCandidate, ...]:
        normalized_scope = str(scope_id or "").strip() or None
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                rows = session.execute(
                    text_factory(_LOAD_VALIDATED_FACTS_SQL),
                    {"scope_id": normalized_scope},
                ).mappings().all()
        except Exception as exc:
            raise MstrBtcAuditStoreError(
                "Failed to load validated MSTR facts: "
                f"{type(exc).__name__}"
            ) from None
        return tuple(_fact_from_row(row) for row in rows)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _insert_or_select(
        self,
        *,
        insert_sql: str,
        select_sql: str,
        params: Mapping[str, Any],
        idempotency_key: str,
        operation: str,
    ) -> StoredMstrBtcAuditRecord:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(insert_sql),
                    dict(params),
                ).mappings().one_or_none()
                if inserted is not None:
                    session.commit()
                    return StoredMstrBtcAuditRecord(
                        row_id=int(inserted["id"]),
                        created=True,
                    )
                existing = session.execute(
                    text_factory(select_sql),
                    {"idempotency_key": idempotency_key},
                ).mappings().one_or_none()
                session.rollback()
        except Exception as exc:
            raise MstrBtcAuditStoreError(
                f"Failed to record MSTR {operation}: "
                f"{type(exc).__name__}"
            ) from None
        if existing is None:
            raise MstrBtcAuditStoreError(
                f"MSTR {operation} conflicts with immutable audit"
            )
        return StoredMstrBtcAuditRecord(
            row_id=int(existing["id"]),
            created=False,
        )

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise MstrBtcAuditStoreError(
                    "MSTR source audit database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise MstrBtcAuditStoreError(
                    "MSTR source audit requires SQLAlchemy "
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
                raise MstrBtcAuditStoreError(
                    "Failed to initialize MSTR source audit database: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise MstrBtcAuditStoreError(
                    "MSTR source audit requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _event_key(candidate: MstrBtcDocumentCandidate) -> str:
    return _digest(
        (
            candidate.scope_id,
            candidate.provider.value,
            candidate.provider_event_id,
            candidate.source_url,
            candidate.transport_fingerprint,
        )
    )


def _fact_key(candidate: MstrBtcFactCandidate) -> str:
    return _digest(
        (
            candidate.scope_id,
            candidate.provider.value,
            candidate.provider_event_id,
            candidate.baseline_state_id,
            candidate.document_fingerprint,
            candidate.holdings_before_btc,
            candidate.holdings_after_btc,
            candidate.acquired_btc,
            candidate.sold_btc,
        )
    )


def _result_key(
    *,
    source_event_id: int,
    status: MstrBtcAuditStatus,
    reason: str,
    baseline_state_id: int | None,
    fact_candidate_id: int | None,
) -> str:
    return _digest(
        (
            source_event_id,
            status.value,
            reason,
            baseline_state_id,
            fact_candidate_id,
        )
    )


def _digest(values: Sequence[object]) -> str:
    encoded = json.dumps(
        list(values),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fact_from_row(row: Mapping[str, Any]) -> MstrBtcFactCandidate:
    evidence = _json_sequence(row.get("evidence"))
    return MstrBtcFactCandidate(
        scope_id=str(row["scope_id"]),
        provider=MstrBtcProvider(str(row["provider"])),
        provider_event_id=str(row["provider_event_id"]),
        baseline_state_id=str(row["baseline_state_id"]),
        holdings_before_btc=int(row["holdings_before_btc"]),
        holdings_after_btc=int(row["holdings_after_btc"]),
        net_change_btc=int(row["net_change_btc"]),
        acquired_btc=(
            int(row["acquired_btc"])
            if row.get("acquired_btc") is not None
            else None
        ),
        sold_btc=(
            int(row["sold_btc"])
            if row.get("sold_btc") is not None
            else None
        ),
        acquired_derivation=MstrBtcValueDerivation(
            str(row["acquired_derivation"])
        ),
        sold_derivation=MstrBtcValueDerivation(
            str(row["sold_derivation"])
        ),
        holdings_crosscheck_difference_btc=int(
            row["holdings_crosscheck_difference_btc"]
        ),
        source_url=str(row["source_url"]),
        filing_url=str(row["filing_url"]),
        published_at=_datetime_value(row["published_at"], "published_at"),
        detected_at=_datetime_value(row["detected_at"], "detected_at"),
        parser_name=str(row["parser_name"]),
        parser_version=str(row["parser_version"]),
        document_fingerprint=str(row["document_fingerprint"]),
        evidence_excerpts=tuple(str(item) for item in evidence),
        attributes=_json_mapping(row.get("attributes")),
    )


def _safe_reason(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("reason is required")
    return redact_sensitive_text(normalized, max_length=240)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer") from None
    if parsed < 1 or str(parsed) != str(value).strip():
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _datetime_value(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    return value


def _json_dumps(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise TypeError(
        f"unsupported JSON value type: {type(value).__name__}"
    )


def _json_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Mapping):
            return dict(decoded)
    raise TypeError("expected a JSON object")


def _json_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Sequence) and not isinstance(
            decoded,
            (str, bytes),
        ):
            return tuple(decoded)
    raise TypeError("expected a JSON array")


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://") :]
    return value
