from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "011_add_earnings_release_catalog.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('earnings_release_catalog') IS NOT NULL AS catalog_table,
    (
        SELECT count(*) = 17
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_release_catalog'
    ) AS catalog_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_release_catalog_event_key'
        )
          AND indisunique
    ) AS catalog_event_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_release_catalog_ticker_date'
        )
          AND indisunique
    ) AS catalog_ticker_date_index,
    to_regclass('ix_earnings_release_catalog_schedule') IS NOT NULL
        AS catalog_schedule_index,
    to_regclass('ix_earnings_release_catalog_readiness') IS NOT NULL
        AS catalog_readiness_index
""".strip()

_UPSERT_SQL = """
INSERT INTO earnings_release_catalog (
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
)
VALUES (
    :event_key,
    :ticker,
    :release_date,
    :market_session,
    :scheduled_release_at,
    :conference_call_at,
    :schedule_status,
    :schedule_source_url,
    :integration_status,
    :document_format,
    CAST(:metric_options AS jsonb),
    CAST(:source_options AS jsonb),
    :notes,
    :verified_at
)
ON CONFLICT (event_key) DO UPDATE
SET
    ticker = EXCLUDED.ticker,
    release_date = EXCLUDED.release_date,
    market_session = EXCLUDED.market_session,
    scheduled_release_at = EXCLUDED.scheduled_release_at,
    conference_call_at = EXCLUDED.conference_call_at,
    schedule_status = EXCLUDED.schedule_status,
    schedule_source_url = EXCLUDED.schedule_source_url,
    integration_status = EXCLUDED.integration_status,
    document_format = EXCLUDED.document_format,
    metric_options = EXCLUDED.metric_options,
    source_options = EXCLUDED.source_options,
    notes = EXCLUDED.notes,
    verified_at = EXCLUDED.verified_at,
    updated_at = now()
RETURNING id
""".strip()

_LOAD_BY_DATE_SQL = """
SELECT
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
FROM earnings_release_catalog
WHERE release_date BETWEEN :date_from AND :date_to
ORDER BY
    release_date,
    CASE market_session
        WHEN 'PRE_MARKET' THEN 1
        WHEN 'POST_MARKET' THEN 2
        ELSE 3
    END,
    COALESCE(scheduled_release_at, conference_call_at),
    ticker
""".strip()

_TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,16}$")


class EarningsMarketSession(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    POST_MARKET = "POST_MARKET"
    UNKNOWN = "UNKNOWN"


class EarningsScheduleStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    ESTIMATED = "ESTIMATED"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class EarningsIntegrationStatus(str, Enum):
    PARSER_ONLY = "PARSER_ONLY"
    NEEDS_DOCUMENT_RESOLVER = "NEEDS_DOCUMENT_RESOLVER"
    NEEDS_LISTING_ADAPTER = "NEEDS_LISTING_ADAPTER"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    RESEARCH_PENDING = "RESEARCH_PENDING"


class EarningsDocumentFormat(str, Enum):
    FULL_HTML = "FULL_HTML"
    PDF = "PDF"
    LINK_ONLY = "LINK_ONLY"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EarningsReleaseCatalogEntry:
    """Reusable research about one scheduled company earnings release."""

    event_key: str
    ticker: str
    release_date: date
    market_session: EarningsMarketSession
    schedule_source_url: str
    integration_status: EarningsIntegrationStatus
    document_format: EarningsDocumentFormat
    verified_at: datetime
    scheduled_release_at: datetime | None = None
    conference_call_at: datetime | None = None
    schedule_status: EarningsScheduleStatus = (
        EarningsScheduleStatus.CONFIRMED
    )
    metric_options: Mapping[str, Any] = field(default_factory=dict)
    source_options: Sequence[Mapping[str, Any]] = field(
        default_factory=tuple
    )
    notes: str | None = None

    def __post_init__(self) -> None:
        event_key = str(self.event_key or "").strip()
        if not event_key:
            raise ValueError("event_key is required")
        object.__setattr__(self, "event_key", event_key)

        ticker = str(self.ticker or "").strip().upper()
        if not _TICKER_RE.fullmatch(ticker):
            raise ValueError("ticker has unsupported characters")
        object.__setattr__(self, "ticker", ticker)

        if not isinstance(self.release_date, date):
            raise TypeError("release_date must be a date")
        if not isinstance(self.market_session, EarningsMarketSession):
            raise TypeError(
                "market_session must be EarningsMarketSession"
            )
        if not isinstance(self.schedule_status, EarningsScheduleStatus):
            raise TypeError(
                "schedule_status must be EarningsScheduleStatus"
            )
        if not isinstance(
            self.integration_status,
            EarningsIntegrationStatus,
        ):
            raise TypeError(
                "integration_status must be EarningsIntegrationStatus"
            )
        if not isinstance(self.document_format, EarningsDocumentFormat):
            raise TypeError(
                "document_format must be EarningsDocumentFormat"
            )

        source_url = str(self.schedule_source_url or "").strip()
        if not source_url.startswith("https://"):
            raise ValueError(
                "schedule_source_url must use https"
            )
        object.__setattr__(
            self,
            "schedule_source_url",
            source_url,
        )
        object.__setattr__(
            self,
            "scheduled_release_at",
            _optional_utc(
                self.scheduled_release_at,
                "scheduled_release_at",
            ),
        )
        object.__setattr__(
            self,
            "conference_call_at",
            _optional_utc(
                self.conference_call_at,
                "conference_call_at",
            ),
        )
        object.__setattr__(
            self,
            "verified_at",
            _required_utc(self.verified_at, "verified_at"),
        )
        object.__setattr__(
            self,
            "metric_options",
            MappingProxyType(dict(self.metric_options)),
        )
        object.__setattr__(
            self,
            "source_options",
            tuple(
                MappingProxyType(dict(option))
                for option in self.source_options
            ),
        )
        notes = str(self.notes or "").strip()
        object.__setattr__(self, "notes", notes or None)


class EarningsReleaseCatalogError(RuntimeError):
    """Value-safe catalog persistence failure."""


class SqlAlchemyEarningsReleaseCatalog:
    """Explicit persistence for non-executable earnings research."""

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
            raise EarningsReleaseCatalogError(
                "Failed to apply earnings catalog migration: "
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
            raise EarningsReleaseCatalogError(
                "Failed to verify earnings catalog schema: "
                f"{type(exc).__name__}"
            ) from None
        expected = (
            "catalog_table",
            "catalog_columns",
            "catalog_event_key_index",
            "catalog_ticker_date_index",
            "catalog_schedule_index",
            "catalog_readiness_index",
        )
        if not all(bool(row.get(name)) for name in expected):
            raise EarningsReleaseCatalogError(
                "Earnings release catalog is not ready"
            )

    def upsert(self, entry: EarningsReleaseCatalogEntry) -> int:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_UPSERT_SQL),
                    _entry_params(entry),
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise EarningsReleaseCatalogError(
                "Failed to save earnings catalog entry: "
                f"{type(exc).__name__}"
            ) from None
        return int(row["id"])

    def load_by_date(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> tuple[EarningsReleaseCatalogEntry, ...]:
        if date_to < date_from:
            raise ValueError("date_to cannot precede date_from")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_LOAD_BY_DATE_SQL),
                    {
                        "date_from": date_from,
                        "date_to": date_to,
                    },
                ).mappings().all()
        except Exception as exc:
            raise EarningsReleaseCatalogError(
                "Failed to load earnings catalog entries: "
                f"{type(exc).__name__}"
            ) from None
        return tuple(_entry_from_row(row) for row in rows)

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
                raise EarningsReleaseCatalogError(
                    "Earnings catalog database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise EarningsReleaseCatalogError(
                    "Earnings catalog requires SQLAlchemy "
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
                raise EarningsReleaseCatalogError(
                    "Failed to initialize earnings catalog: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise EarningsReleaseCatalogError(
                    "Earnings catalog requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _entry_params(
    entry: EarningsReleaseCatalogEntry,
) -> dict[str, Any]:
    return {
        "event_key": entry.event_key,
        "ticker": entry.ticker,
        "release_date": entry.release_date,
        "market_session": entry.market_session.value,
        "scheduled_release_at": entry.scheduled_release_at,
        "conference_call_at": entry.conference_call_at,
        "schedule_status": entry.schedule_status.value,
        "schedule_source_url": entry.schedule_source_url,
        "integration_status": entry.integration_status.value,
        "document_format": entry.document_format.value,
        "metric_options": json.dumps(
            dict(entry.metric_options),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "source_options": json.dumps(
            [dict(option) for option in entry.source_options],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "notes": entry.notes,
        "verified_at": entry.verified_at,
    }


def _entry_from_row(row: Any) -> EarningsReleaseCatalogEntry:
    metric_options = row.get("metric_options") or {}
    source_options = row.get("source_options") or []
    if isinstance(metric_options, str):
        metric_options = json.loads(metric_options)
    if isinstance(source_options, str):
        source_options = json.loads(source_options)
    return EarningsReleaseCatalogEntry(
        event_key=str(row["event_key"]),
        ticker=str(row["ticker"]),
        release_date=row["release_date"],
        market_session=EarningsMarketSession(
            str(row["market_session"])
        ),
        scheduled_release_at=row.get("scheduled_release_at"),
        conference_call_at=row.get("conference_call_at"),
        schedule_status=EarningsScheduleStatus(
            str(row["schedule_status"])
        ),
        schedule_source_url=str(row["schedule_source_url"]),
        integration_status=EarningsIntegrationStatus(
            str(row["integration_status"])
        ),
        document_format=EarningsDocumentFormat(
            str(row["document_format"])
        ),
        metric_options=dict(metric_options),
        source_options=tuple(
            dict(option)
            for option in source_options
        ),
        notes=row.get("notes"),
        verified_at=row["verified_at"],
    )


def _required_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_utc(
    value: datetime | None,
    name: str,
) -> datetime | None:
    if value is None:
        return None
    return _required_utc(value, name)


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
