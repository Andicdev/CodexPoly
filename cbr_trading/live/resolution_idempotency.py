from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    OrderTemplate,
    RepriceOnTickChange,
)
from cbr_trading.execution.prepared_executor import PreparationContext
from cbr_trading.secret_guard import redact_sensitive_text


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "003_add_resolution_execution_claims.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_execution_claims') IS NOT NULL AS claims_table,
    (
        SELECT count(*) = 22
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_execution_claims'
          AND column_name = ANY(ARRAY[
              'id', 'idempotency_key', 'scope_id', 'template_id',
              'strategy_id', 'source', 'source_reference', 'account_name',
              'condition_id', 'outcome', 'side', 'desired_price',
              'effective_price', 'quantity', 'notional', 'status',
              'result', 'error', 'metadata', 'created_at', 'updated_at',
              'completed_at'
          ])
    ) AS claims_columns,
    COALESCE(
        (
            SELECT is_identity = 'YES'
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'resolution_execution_claims'
              AND column_name = 'id'
        ),
        false
    ) AS id_generated,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_resolution_execution_claims_key'
        )
          AND indrelid = to_regclass(
            'resolution_execution_claims'
        )
          AND indisunique
    ) AS key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_resolution_execution_claims_scope_template'
        )
          AND indrelid = to_regclass(
            'resolution_execution_claims'
        )
          AND indisunique
    ) AS scope_template_index
""".strip()

_INSERT_SQL = """
INSERT INTO resolution_execution_claims (
    idempotency_key,
    scope_id,
    template_id,
    strategy_id,
    source,
    source_reference,
    account_name,
    condition_id,
    outcome,
    side,
    desired_price,
    effective_price,
    quantity,
    notional,
    metadata
)
VALUES (
    :idempotency_key,
    :scope_id,
    :template_id,
    :strategy_id,
    :source,
    :source_reference,
    :account_name,
    :condition_id,
    :outcome,
    :side,
    :desired_price,
    :effective_price,
    :quantity,
    :notional,
    CAST(:metadata AS jsonb)
)
ON CONFLICT DO NOTHING
RETURNING id
""".strip()

_SELECT_EXISTING_SQL = """
SELECT id, status
FROM resolution_execution_claims
WHERE idempotency_key = :idempotency_key
   OR (
       scope_id = :scope_id
       AND template_id = :template_id
   )
ORDER BY id
LIMIT 1
""".strip()

_COMPLETE_SQL = """
UPDATE resolution_execution_claims
SET
    status = :status,
    result = CAST(:result AS jsonb),
    error = :error,
    updated_at = now(),
    completed_at = now()
WHERE id = :claim_id
  AND status = 'PENDING'
RETURNING id
""".strip()

_RECORD_CLEANUP_SQL = """
UPDATE resolution_execution_claims
SET
    result = COALESCE(result, '{}'::jsonb)
        || jsonb_build_object(
            'smoke_cleanup',
            CAST(:cleanup AS jsonb)
        ),
    updated_at = now()
WHERE id = :claim_id
  AND status IN ('EXECUTED', 'ERROR')
RETURNING id
""".strip()

_FINAL_STATUSES = frozenset(
    {"EXECUTED", "REJECTED", "ERROR", "EXPIRED"}
)


class ResolutionExecutionLedgerError(RuntimeError):
    """Sanitized failure while reserving or completing an execution claim."""


@dataclass(frozen=True)
class ResolutionExecutionClaim:
    claim_id: int
    idempotency_key: str
    scope_id: str
    template_id: str


class SqlAlchemyResolutionExecutionLedger:
    """Atomic source-neutral idempotency claims for PreparedExecutor."""

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
        """Apply only migration 003; live runners never call this method."""

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                migration_sql = _MIGRATION_PATH.read_text(
                    encoding="utf-8"
                )
                session.execute(text_factory(migration_sql))
                session.commit()
        except Exception as exc:
            raise ResolutionExecutionLedgerError(
                "Failed to apply additive resolution execution migration: "
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
            raise ResolutionExecutionLedgerError(
                "Failed to verify resolution execution schema: "
                f"{type(exc).__name__}"
            ) from exc

        if not all(
            bool(row.get(name))
            for name in (
                "claims_table",
                "claims_columns",
                "id_generated",
                "key_index",
                "scope_template_index",
            )
        ):
            raise ResolutionExecutionLedgerError(
                "Resolution execution claims table is not ready"
            )

    def reserve_many(
        self,
        *,
        context: PreparationContext,
        templates: Sequence[OrderTemplate],
        effective_prices: Mapping[str, Decimal],
    ) -> tuple[ResolutionExecutionClaim, ...]:
        template_rows = tuple(templates)
        if not template_rows:
            return ()
        template_ids = [template.template_id for template in template_rows]
        if len(template_ids) != len(set(template_ids)):
            raise ResolutionExecutionLedgerError(
                "Resolution execution templates must be unique"
            )
        if set(effective_prices) != set(template_ids):
            raise ResolutionExecutionLedgerError(
                "Effective prices must match resolution templates exactly"
            )

        session_factory, text_factory = self._resolve_dependencies()
        claims: list[ResolutionExecutionClaim] = []
        try:
            with session_factory() as session:
                for template in template_rows:
                    idempotency_key = make_resolution_idempotency_key(
                        scope_id=context.scope_id,
                        template_id=template.template_id,
                    )
                    params = _claim_params(
                        context=context,
                        template=template,
                        effective_price=effective_prices[
                            template.template_id
                        ],
                        idempotency_key=idempotency_key,
                    )
                    inserted = session.execute(
                        text_factory(_INSERT_SQL),
                        params,
                    ).mappings().one_or_none()
                    if inserted is None:
                        existing = session.execute(
                            text_factory(_SELECT_EXISTING_SQL),
                            {
                                "idempotency_key": idempotency_key,
                                "scope_id": context.scope_id,
                                "template_id": template.template_id,
                            },
                        ).mappings().one_or_none()
                        session.rollback()
                        status = (
                            str(existing.get("status") or "").upper()
                            if existing is not None
                            else "UNKNOWN"
                        )
                        raise ResolutionExecutionLedgerError(
                            "Resolution execution is already claimed "
                            f"for template {template.template_id!r} "
                            f"(status={status})"
                        )
                    claims.append(
                        ResolutionExecutionClaim(
                            claim_id=int(inserted["id"]),
                            idempotency_key=idempotency_key,
                            scope_id=context.scope_id,
                            template_id=template.template_id,
                        )
                    )
                session.commit()
        except ResolutionExecutionLedgerError:
            raise
        except Exception as exc:
            raise ResolutionExecutionLedgerError(
                "Failed to reserve resolution execution claims: "
                f"{type(exc).__name__}"
            ) from exc
        return tuple(claims)

    def complete(
        self,
        claim_id: int,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in _FINAL_STATUSES:
            raise ValueError("Unsupported resolution execution status")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                updated = session.execute(
                    text_factory(_COMPLETE_SQL),
                    {
                        "claim_id": int(claim_id),
                        "status": normalized_status,
                        "result": _json_dumps(result or {}),
                        "error": _safe_error(error),
                    },
                ).mappings().one_or_none()
                if updated is None:
                    session.rollback()
                    raise ResolutionExecutionLedgerError(
                        "Resolution execution claim is not pending"
                    )
                session.commit()
        except ResolutionExecutionLedgerError:
            raise
        except Exception as exc:
            raise ResolutionExecutionLedgerError(
                "Failed to complete resolution execution claim: "
                f"{type(exc).__name__}"
            ) from exc

    def record_cleanup(
        self,
        claim_id: int,
        *,
        cleanup: Mapping[str, Any],
    ) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                updated = session.execute(
                    text_factory(_RECORD_CLEANUP_SQL),
                    {
                        "claim_id": int(claim_id),
                        "cleanup": _json_dumps(cleanup),
                    },
                ).mappings().one_or_none()
                if updated is None:
                    session.rollback()
                    raise ResolutionExecutionLedgerError(
                        "Resolution execution claim cannot record cleanup"
                    )
                session.commit()
        except ResolutionExecutionLedgerError:
            raise
        except Exception as exc:
            raise ResolutionExecutionLedgerError(
                "Failed to record resolution execution cleanup: "
                f"{type(exc).__name__}"
            ) from exc

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
                raise ResolutionExecutionLedgerError(
                    "Trading database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
                from sqlalchemy.pool import NullPool
            except ImportError as exc:
                raise ResolutionExecutionLedgerError(
                    "Resolution execution ledger requires SQLAlchemy "
                    "and a PostgreSQL driver"
                ) from exc
            try:
                self._engine = create_engine(
                    _normalize_database_url(self._database_url),
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                    poolclass=NullPool,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise ResolutionExecutionLedgerError(
                    "Failed to initialize resolution ledger database: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory

        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise ResolutionExecutionLedgerError(
                    "Resolution execution ledger requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def make_resolution_idempotency_key(
    *,
    scope_id: str,
    template_id: str,
) -> str:
    scope = str(scope_id or "").strip()
    template = str(template_id or "").strip()
    if not scope or not template:
        raise ValueError("scope_id and template_id are required")
    digest = hashlib.sha256(
        f"{scope}|{template}".encode("utf-8")
    ).hexdigest()
    return f"resolution:v1:{digest}"


def _claim_params(
    *,
    context: PreparationContext,
    template: OrderTemplate,
    effective_price: Decimal,
    idempotency_key: str,
) -> dict[str, Any]:
    policy = template.lifecycle_policy
    if isinstance(policy, KeepOpenPolicy):
        lifecycle: dict[str, Any] = {"kind": policy.kind}
    elif isinstance(policy, RepriceOnTickChange):
        lifecycle = {
            "kind": policy.kind,
            "old_tick": str(policy.old_tick),
            "new_tick": str(policy.new_tick),
            "max_reprices": policy.max_reprices,
        }
    else:
        raise TypeError("unsupported lifecycle policy")
    return {
        "idempotency_key": idempotency_key,
        "scope_id": context.scope_id,
        "template_id": template.template_id,
        "strategy_id": template.strategy_id,
        "source": context.source,
        "source_reference": context.source_reference,
        "account_name": template.account_name,
        "condition_id": template.condition_id,
        "outcome": template.outcome.value,
        "side": template.side.value,
        "desired_price": template.desired_price,
        "effective_price": Decimal(str(effective_price)),
        "quantity": template.quantity,
        "notional": template.notional,
        "metadata": _json_dumps(
            {
                "rule_id": template.metadata.get("rule_id"),
                "rule_key": template.metadata.get("rule_key"),
                "lifecycle": lifecycle,
            }
        ),
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _safe_error(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return redact_sensitive_text(normalized) if normalized else None


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
