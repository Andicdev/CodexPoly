from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbr_trading.notifications.contracts import SourceEventNotification


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "010_add_source_notification_outbox.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('source_notification_outbox') IS NOT NULL AS outbox_table,
    (
        SELECT count(*) = 15
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'source_notification_outbox'
    ) AS outbox_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_source_notification_outbox_key'
        )
          AND indisunique
    ) AS outbox_key_index,
    to_regclass('ix_source_notification_outbox_dispatch') IS NOT NULL
        AS outbox_dispatch_index
""".strip()

_ENQUEUE_SQL = """
INSERT INTO source_notification_outbox (
    notification_key,
    source_name,
    scope_id,
    event_kind,
    message_text,
    source_url,
    available_at
)
VALUES (
    :notification_key,
    :source_name,
    :scope_id,
    :event_kind,
    :message_text,
    :source_url,
    now() + CAST(:delivery_delay_seconds AS double precision)
        * interval '1 second'
)
ON CONFLICT (notification_key) DO NOTHING
RETURNING id
""".strip()

_SELECT_ID_SQL = """
SELECT id
FROM source_notification_outbox
WHERE notification_key = :notification_key
LIMIT 1
""".strip()

_CLAIM_SQL = """
WITH candidate AS (
    SELECT id
    FROM source_notification_outbox
    WHERE (
        status IN ('PENDING', 'FAILED')
        OR (
            status = 'SENDING'
            AND lease_until < now()
        )
    )
      AND available_at <= now()
    ORDER BY available_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE source_notification_outbox AS outbox
SET
    status = 'SENDING',
    attempt_count = outbox.attempt_count + 1,
    lease_until = now()
        + CAST(:lease_seconds AS double precision)
            * interval '1 second',
    last_error_code = NULL,
    updated_at = now()
FROM candidate
WHERE outbox.id = candidate.id
RETURNING
    outbox.id,
    outbox.notification_key,
    outbox.message_text,
    outbox.attempt_count
""".strip()

_MARK_SENT_SQL = """
UPDATE source_notification_outbox
SET
    status = 'SENT',
    lease_until = NULL,
    last_error_code = NULL,
    sent_at = now(),
    updated_at = now()
WHERE id = :row_id
  AND status = 'SENDING'
RETURNING id
""".strip()

_MARK_FAILED_SQL = """
UPDATE source_notification_outbox
SET
    status = 'FAILED',
    available_at = now()
        + CAST(:retry_delay_seconds AS double precision)
            * interval '1 second',
    lease_until = NULL,
    last_error_code = :error_code,
    updated_at = now()
WHERE id = :row_id
  AND status = 'SENDING'
RETURNING id
""".strip()


class NotificationOutboxStoreError(RuntimeError):
    """Value-safe failure while persisting or claiming notifications."""


@dataclass(frozen=True)
class StoredNotification:
    row_id: int
    created: bool


@dataclass(frozen=True)
class ClaimedNotification:
    row_id: int
    notification_key: str
    message_text: str
    attempt_count: int


class SqlAlchemyNotificationOutboxStore:
    """Durable idempotent source-event notification queue."""

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
            raise NotificationOutboxStoreError(
                "Failed to apply notification outbox migration: "
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
            raise NotificationOutboxStoreError(
                "Failed to verify notification outbox schema: "
                f"{type(exc).__name__}"
            ) from None
        expected = (
            "outbox_table",
            "outbox_columns",
            "outbox_key_index",
            "outbox_dispatch_index",
        )
        if not all(bool(row.get(name)) for name in expected):
            raise NotificationOutboxStoreError(
                "Source notification outbox is not ready"
            )

    def enqueue(
        self,
        notification: SourceEventNotification,
        *,
        delivery_delay_seconds: float = 0,
    ) -> StoredNotification:
        if delivery_delay_seconds < 0:
            raise ValueError("delivery_delay_seconds cannot be negative")
        params = {
            "notification_key": notification.notification_key,
            "source_name": notification.source_name,
            "scope_id": notification.scope_id,
            "event_kind": notification.event_kind,
            "message_text": notification.message_text,
            "source_url": notification.source_url,
            "delivery_delay_seconds": float(delivery_delay_seconds),
        }
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_ENQUEUE_SQL),
                    params,
                ).mappings().one_or_none()
                created = inserted is not None
                if inserted is None:
                    inserted = session.execute(
                        text_factory(_SELECT_ID_SQL),
                        {
                            "notification_key": (
                                notification.notification_key
                            )
                        },
                    ).mappings().one()
                session.commit()
        except Exception as exc:
            raise NotificationOutboxStoreError(
                "Failed to enqueue source notification: "
                f"{type(exc).__name__}"
            ) from None
        return StoredNotification(
            row_id=int(inserted["id"]),
            created=created,
        )

    def claim_next(
        self,
        *,
        lease_seconds: float,
    ) -> ClaimedNotification | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_CLAIM_SQL),
                    {"lease_seconds": float(lease_seconds)},
                ).mappings().one_or_none()
                session.commit()
        except Exception as exc:
            raise NotificationOutboxStoreError(
                "Failed to claim source notification: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            return None
        return ClaimedNotification(
            row_id=int(row["id"]),
            notification_key=str(row["notification_key"]),
            message_text=str(row["message_text"]),
            attempt_count=int(row["attempt_count"]),
        )

    def mark_sent(self, row_id: int) -> None:
        self._transition(
            _MARK_SENT_SQL,
            {"row_id": int(row_id)},
            failure="Failed to mark source notification sent",
        )

    def mark_failed(
        self,
        row_id: int,
        *,
        error_code: str,
        retry_delay_seconds: float,
    ) -> None:
        normalized_error = str(error_code or "").strip()
        if not normalized_error:
            raise ValueError("error_code is required")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        self._transition(
            _MARK_FAILED_SQL,
            {
                "row_id": int(row_id),
                "error_code": normalized_error[:100],
                "retry_delay_seconds": float(retry_delay_seconds),
            },
            failure="Failed to mark source notification failed",
        )

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _transition(
        self,
        sql: str,
        params: dict[str, object],
        *,
        failure: str,
    ) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(sql),
                    params,
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    raise NotificationOutboxStoreError(
                        "Notification outbox claim is no longer current"
                    )
                session.commit()
        except NotificationOutboxStoreError:
            raise
        except Exception as exc:
            raise NotificationOutboxStoreError(
                f"{failure}: {type(exc).__name__}"
            ) from None

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise NotificationOutboxStoreError(
                    "Notification outbox database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise NotificationOutboxStoreError(
                    "Notification outbox requires SQLAlchemy "
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
                raise NotificationOutboxStoreError(
                    "Failed to initialize notification outbox database: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise NotificationOutboxStoreError(
                    "Notification outbox requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url
