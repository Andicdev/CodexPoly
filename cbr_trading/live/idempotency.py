from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from cbr_trading.pipeline import OrderIntent
from cbr_trading.rule_repository import (
    CBR_CHANGE_METRIC,
    CBR_EXECUTION_PATH,
    CBR_TICKER,
)
from cbr_trading.secret_guard import redact_sensitive_text


_TABLE_READY_SQL = """
SELECT
    to_regclass('news_trade_confirmations') IS NOT NULL AS table_exists,
    (
        SELECT count(*) = 14
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'news_trade_confirmations'
          AND column_name = ANY(ARRAY[
              'id',
              'idempotency_key',
              'status',
              'sub_id',
              'ticker',
              'metric_key',
              'execution_path',
              'action',
              'account_name',
              'condition_id',
              'order_qty',
              'order_price',
              'source_url',
              'payload'
          ])
    ) AS columns_ready,
    EXISTS (
        SELECT 1
        FROM pg_index index_record
        JOIN pg_class table_record
          ON table_record.oid = index_record.indrelid
        JOIN pg_namespace namespace_record
          ON namespace_record.oid = table_record.relnamespace
        JOIN pg_attribute column_record
          ON column_record.attrelid = table_record.oid
         AND column_record.attnum = index_record.indkey[0]
        WHERE namespace_record.nspname = current_schema()
          AND table_record.relname = 'news_trade_confirmations'
          AND index_record.indisunique
          AND index_record.indnkeyatts = 1
          AND column_record.attname = 'idempotency_key'
    ) AS key_unique,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'news_trade_confirmations'
          AND column_name = 'id'
          AND (
              column_default IS NOT NULL
              OR is_identity = 'YES'
          )
    ) AS id_generated
""".strip()

_INSERT_CLAIM_SQL = """
INSERT INTO news_trade_confirmations (
    idempotency_key,
    status,
    sub_id,
    ticker,
    metric_key,
    execution_path,
    action,
    account_name,
    condition_id,
    order_qty,
    order_price,
    source_url,
    payload
)
VALUES (
    :idempotency_key,
    'PENDING',
    :sub_id,
    :ticker,
    :metric_key,
    :execution_path,
    :action,
    :account_name,
    :condition_id,
    :order_qty,
    :order_price,
    :source_url,
    CAST(:payload AS jsonb)
)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id, status
""".strip()

_SELECT_EXISTING_SQL = """
SELECT id, status, result, error
FROM news_trade_confirmations
WHERE idempotency_key = :idempotency_key
""".strip()

_COMPLETE_SQL = """
UPDATE news_trade_confirmations
SET
    status = :status,
    result = CAST(:result AS jsonb),
    error = :error,
    updated_at = now()
WHERE id = :claim_id
  AND status = 'PENDING'
""".strip()


class ExecutionLedgerError(RuntimeError):
    """Safe failure while checking or updating order idempotency."""


@dataclass(frozen=True)
class ExecutionClaim:
    acquired: bool
    idempotency_key: str
    claim_id: int
    existing_status: str | None = None
    existing_order_id: str | None = None
    existing_error: str | None = None


class SqlAlchemyExecutionLedger:
    """Persistent one-order claim using the existing confirmation table."""

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

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_TABLE_READY_SQL)
                ).mappings().one()
        except Exception as exc:
            raise ExecutionLedgerError(
                "Failed to verify execution ledger: "
                f"{type(exc).__name__}"
            ) from exc

        if (
            not row.get("table_exists")
            or not row.get("columns_ready")
            or not row.get("key_unique")
            or not row.get("id_generated")
        ):
            raise ExecutionLedgerError(
                "news_trade_confirmations is not ready for safe "
                "idempotency claims"
            )
        self.verify_reservation_compatibility()

    def verify_reservation_compatibility(self) -> None:
        """Execute the real PENDING insert shape and always roll it back."""
        session_factory, text_factory = self._resolve_dependencies()
        probe_intent = OrderIntent(
            rule_id=None,
            rule_key="schema_probe",
            account_name="schema_probe",
            condition_id="0x" + ("0" * 64),
            action="YES",
            quantity=1,
            limit_price="0.01",
            ready=True,
            reason="schema_probe",
        )
        params = _claim_params(
            release_url=f"cbr-schema-probe://{uuid4().hex}",
            intent=probe_intent,
        )
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_CLAIM_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is None:
                    raise ExecutionLedgerError(
                        "Execution ledger reservation probe conflicted"
                    )
                session.rollback()
        except ExecutionLedgerError:
            raise
        except Exception as exc:
            raise ExecutionLedgerError(
                "Execution ledger reservation probe failed: "
                f"{type(exc).__name__}"
            ) from exc

    def reserve_many(
        self,
        *,
        release_url: str,
        intents: list[OrderIntent] | tuple[OrderIntent, ...],
    ) -> tuple[ExecutionClaim, ...]:
        if not intents:
            return ()
        session_factory, text_factory = self._resolve_dependencies()
        claims: list[ExecutionClaim] = []
        try:
            with session_factory() as session:
                for intent in intents:
                    params = _claim_params(
                        release_url=release_url,
                        intent=intent,
                    )
                    inserted = session.execute(
                        text_factory(_INSERT_CLAIM_SQL),
                        params,
                    ).mappings().one_or_none()
                    if inserted is None:
                        existing = session.execute(
                            text_factory(_SELECT_EXISTING_SQL),
                            {
                                "idempotency_key": params[
                                    "idempotency_key"
                                ]
                            },
                        ).mappings().one()
                        session.rollback()
                        raise ExecutionLedgerError(
                            "Live order reservation already exists "
                            f"for rule={intent.rule_id!r} "
                            f"action={intent.action} "
                            f"status={existing.get('status') or 'UNKNOWN'}"
                        )
                    claims.append(
                        ExecutionClaim(
                            acquired=True,
                            idempotency_key=str(
                                params["idempotency_key"]
                            ),
                            claim_id=int(inserted["id"]),
                        )
                    )
                session.commit()
                return tuple(claims)
        except ExecutionLedgerError:
            raise
        except Exception as exc:
            raise ExecutionLedgerError(
                "Failed to reserve live order idempotency: "
                f"{type(exc).__name__}"
            ) from exc

    def claim(
        self,
        *,
        release_url: str,
        intent: OrderIntent,
    ) -> ExecutionClaim:
        """Compatibility wrapper for one pre-release reservation."""
        return self.reserve_many(
            release_url=release_url,
            intents=(intent,),
        )[0]

    def complete(
        self,
        *,
        claim_id: int,
        status: str,
        result: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in {
            "EXECUTED",
            "REJECTED",
            "EXPIRED",
            "ERROR",
        }:
            raise ValueError(
                f"Unsupported execution ledger status: {status!r}"
            )

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                updated = session.execute(
                    text_factory(_COMPLETE_SQL),
                    {
                        "claim_id": int(claim_id),
                        "status": normalized_status,
                        "result": json.dumps(
                            dict(result),
                            ensure_ascii=False,
                            default=str,
                        ),
                        "error": _safe_error(error),
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise ExecutionLedgerError(
                        "Execution reservation was not in PENDING state"
                    )
                session.commit()
        except ExecutionLedgerError:
            raise
        except Exception as exc:
            raise ExecutionLedgerError(
                "Failed to complete live order idempotency: "
                f"{type(exc).__name__}"
            ) from exc

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory

        if session_factory is None:
            if not self._database_url:
                raise ExecutionLedgerError(
                    "Execution ledger database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise ExecutionLedgerError(
                    "Execution ledger requires SQLAlchemy"
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
                raise ExecutionLedgerError(
                    "Failed to initialize execution ledger: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory

        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise ExecutionLedgerError(
                    "Execution ledger requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory

        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def make_idempotency_key(
    *,
    release_url: str,
    intent: OrderIntent,
) -> str:
    raw = "|".join(
        (
            "cbr_auto_v1",
            str(release_url or "").strip(),
            str(intent.rule_id),
            str(intent.rule_key),
            str(intent.action).upper(),
            str(intent.account_name).casefold(),
            str(intent.condition_id).casefold(),
            str(intent.quantity),
            str(intent.limit_price),
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"cbr_auto:v1:{digest}"


def _claim_params(
    *,
    release_url: str,
    intent: OrderIntent,
) -> dict[str, Any]:
    key = make_idempotency_key(
        release_url=release_url,
        intent=intent,
    )
    payload = {
        "component": "cbr_trading",
        "version": 2,
        "release_url": str(release_url),
        "rule_id": intent.rule_id,
        "rule_key": intent.rule_key,
        "action": intent.action,
    }
    return {
        "idempotency_key": key,
        "sub_id": _integer_or_none(intent.rule_id),
        "ticker": CBR_TICKER,
        "metric_key": CBR_CHANGE_METRIC,
        "execution_path": CBR_EXECUTION_PATH,
        "action": intent.action,
        "account_name": intent.account_name,
        "condition_id": intent.condition_id,
        "order_qty": intent.quantity,
        "order_price": intent.limit_price,
        "source_url": str(release_url),
        "payload": json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        ),
    }


def _integer_or_none(value: int | str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    return redact_sensitive_text(value, max_length=500)


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
