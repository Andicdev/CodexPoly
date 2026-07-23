from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cbr_trading.pipeline import OrderIntent
from cbr_trading.rule_repository import (
    CBR_CHANGE_METRIC,
    CBR_EXECUTION_PATH,
    CBR_TICKER,
)


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
    'EXECUTING',
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
  AND status = 'EXECUTING'
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

    def claim(
        self,
        *,
        release_url: str,
        intent: OrderIntent,
    ) -> ExecutionClaim:
        session_factory, text_factory = self._resolve_dependencies()
        key = make_idempotency_key(
            release_url=release_url,
            intent=intent,
        )
        payload = {
            "component": "cbr_trading",
            "version": 1,
            "release_url": str(release_url),
            "rule_id": intent.rule_id,
            "rule_key": intent.rule_key,
            "action": intent.action,
        }
        params = {
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

        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_CLAIM_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is not None:
                    session.commit()
                    return ExecutionClaim(
                        acquired=True,
                        idempotency_key=key,
                        claim_id=int(inserted["id"]),
                    )

                existing = session.execute(
                    text_factory(_SELECT_EXISTING_SQL),
                    {"idempotency_key": key},
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise ExecutionLedgerError(
                "Failed to claim live order idempotency: "
                f"{type(exc).__name__}"
            ) from exc

        result = existing.get("result")
        order_id = (
            str(result.get("order_id"))
            if isinstance(result, Mapping)
            and result.get("order_id")
            else None
        )
        return ExecutionClaim(
            acquired=False,
            idempotency_key=key,
            claim_id=int(existing["id"]),
            existing_status=str(existing.get("status") or "UNKNOWN"),
            existing_order_id=order_id,
            existing_error=(
                str(existing.get("error"))
                if existing.get("error")
                else None
            ),
        )

    def complete(
        self,
        *,
        claim_id: int,
        status: str,
        result: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in {"EXECUTED", "REJECTED", "FAILED"}:
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
                        "Execution claim was not in EXECUTING state"
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


def _integer_or_none(value: int | str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(str(value).split())[:500]


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
