from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
)


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "013_add_resolution_runtime_heartbeats.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_runtime_heartbeats') IS NOT NULL
        AS heartbeat_table,
    (
        SELECT count(*) = 10
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_runtime_heartbeats'
    ) AS heartbeat_columns,
    to_regclass('ux_resolution_runtime_heartbeats_key') IS NOT NULL
        AS heartbeat_key_index,
    to_regclass('ix_resolution_runtime_heartbeats_seen') IS NOT NULL
        AS heartbeat_seen_index
""".strip()

_UPSERT_SQL = """
INSERT INTO resolution_runtime_heartbeats (
    runtime_key,
    mode,
    supervision_enabled,
    trading_enabled,
    process_started_at,
    last_seen_at,
    metadata
)
VALUES (
    :runtime_key,
    :mode,
    :supervision_enabled,
    :trading_enabled,
    :process_started_at,
    :last_seen_at,
    CAST(:metadata AS jsonb)
)
ON CONFLICT (runtime_key) DO UPDATE
SET
    mode = EXCLUDED.mode,
    supervision_enabled = EXCLUDED.supervision_enabled,
    trading_enabled = EXCLUDED.trading_enabled,
    process_started_at = EXCLUDED.process_started_at,
    last_seen_at = EXCLUDED.last_seen_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
RETURNING id
""".strip()


class ResolutionRuntimeStoreError(RuntimeError):
    """Sanitized persistence failure for resolution liveness."""


class SqlAlchemyResolutionRuntimeStore:
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
            raise ResolutionRuntimeStoreError(
                "Failed to apply resolution runtime migration: "
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
            raise ResolutionRuntimeStoreError(
                "Failed to verify resolution runtime schema: "
                f"{type(exc).__name__}"
            ) from None
        if not all(bool(value) for value in row.values()):
            raise ResolutionRuntimeStoreError(
                "Resolution runtime heartbeat schema is not ready"
            )

    def heartbeat(
        self,
        *,
        runtime_key: str,
        mode: HostedResolutionMode,
        supervision_enabled: bool,
        trading_enabled: bool,
        process_started_at: datetime,
        seen_at: datetime,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        key = str(runtime_key or "").strip()
        if not key:
            raise ValueError("runtime_key is required")
        started = _as_utc(process_started_at)
        seen = _as_utc(seen_at)
        if seen < started:
            raise ValueError("seen_at cannot be before process_started_at")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(_UPSERT_SQL),
                    {
                        "runtime_key": key,
                        "mode": mode.value,
                        "supervision_enabled": bool(
                            supervision_enabled
                        ),
                        "trading_enabled": bool(trading_enabled),
                        "process_started_at": started,
                        "last_seen_at": seen,
                        "metadata": json.dumps(
                            dict(metadata or {}),
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                    },
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise ResolutionRuntimeStoreError(
                "Failed to persist resolution runtime heartbeat: "
                f"{type(exc).__name__}"
            ) from None

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
                raise ResolutionRuntimeStoreError(
                    "Resolution runtime database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise ResolutionRuntimeStoreError(
                    "Resolution runtime requires SQLAlchemy "
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
                raise ResolutionRuntimeStoreError(
                    "Resolution runtime requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _as_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("runtime heartbeat clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url
