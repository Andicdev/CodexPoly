from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from cbr_trading.mstr_btc.contracts import (
    MstrBtcHoldingsBaseline,
    MstrBtcHoldingsObservation,
    MstrBtcProvider,
)


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "008_add_mstr_btc_holdings_state.sql"
)
_SET_READ_ONLY_SQL = "SET TRANSACTION READ ONLY"

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('mstr_btc_holdings_state') IS NOT NULL AS state_table,
    (
        SELECT count(*) = 12
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mstr_btc_holdings_state'
    ) AS state_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_mstr_btc_holdings_state_provider_event'
        )
          AND indisunique
    ) AS provider_event_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ix_mstr_btc_holdings_state_pin'
        )
    ) AS pin_index,
    EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = to_regclass('mstr_btc_holdings_state')
          AND tgname = 'trg_mstr_btc_holdings_state_append_only'
          AND NOT tgisinternal
    ) AS append_only_trigger
""".strip()

_INSERT_STATE_SQL = """
INSERT INTO mstr_btc_holdings_state (
    holdings_btc,
    as_of,
    observed_at,
    provider,
    provider_event_id,
    source_url,
    document_fingerprint,
    predecessor_state_id,
    validation_status,
    attributes
)
VALUES (
    :holdings_btc,
    :as_of,
    :observed_at,
    :provider,
    :provider_event_id,
    :source_url,
    :document_fingerprint,
    :predecessor_state_id,
    :validation_status,
    CAST(:attributes AS jsonb)
)
ON CONFLICT (provider, provider_event_id) DO NOTHING
RETURNING id
""".strip()

_SELECT_PROVIDER_EVENT_SQL = """
SELECT
    id,
    holdings_btc,
    as_of,
    observed_at,
    provider,
    provider_event_id,
    source_url,
    document_fingerprint,
    predecessor_state_id,
    validation_status,
    attributes
FROM mstr_btc_holdings_state
WHERE provider = :provider
  AND provider_event_id = :provider_event_id
LIMIT 1
""".strip()

_PIN_BASELINE_SQL = """
SELECT
    id,
    holdings_btc,
    as_of,
    provider,
    provider_event_id,
    source_url
FROM mstr_btc_holdings_state
WHERE validation_status = 'VALIDATED'
  AND as_of < :before
  AND observed_at < :before
ORDER BY
    as_of DESC,
    observed_at DESC,
    id DESC
LIMIT 1
""".strip()


class MstrBtcHoldingsStoreError(RuntimeError):
    """Sanitized failure in MSTR holdings persistence."""


class MstrBtcBaselineNotFound(MstrBtcHoldingsStoreError):
    """No validated holdings state existed before the requested boundary."""


@dataclass(frozen=True)
class StoredMstrBtcHoldingsState:
    row_id: int
    created: bool


class SqlAlchemyMstrBtcHoldingsStore:
    """Explicit migration and append-only holdings state persistence."""

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
            raise MstrBtcHoldingsStoreError(
                "Failed to apply additive MSTR holdings migration: "
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
            raise MstrBtcHoldingsStoreError(
                "Failed to verify MSTR holdings schema: "
                f"{type(exc).__name__}"
            ) from None
        expected = (
            "state_table",
            "state_columns",
            "provider_event_index",
            "pin_index",
            "append_only_trigger",
        )
        if not all(bool(row.get(name)) for name in expected):
            raise MstrBtcHoldingsStoreError(
                "MSTR BTC holdings state table is not ready"
            )

    def record_state(
        self,
        observation: MstrBtcHoldingsObservation,
    ) -> StoredMstrBtcHoldingsState:
        if not isinstance(observation, MstrBtcHoldingsObservation):
            raise TypeError(
                "observation must be MstrBtcHoldingsObservation"
            )
        params = _observation_params(observation)
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                inserted = session.execute(
                    text_factory(_INSERT_STATE_SQL),
                    params,
                ).mappings().one_or_none()
                if inserted is not None:
                    session.commit()
                    return StoredMstrBtcHoldingsState(
                        row_id=int(inserted["id"]),
                        created=True,
                    )
                existing = session.execute(
                    text_factory(_SELECT_PROVIDER_EVENT_SQL),
                    {
                        "provider": observation.provider.value,
                        "provider_event_id": observation.provider_event_id,
                    },
                ).mappings().one()
                if not _observation_matches_row(observation, existing):
                    session.rollback()
                    raise MstrBtcHoldingsStoreError(
                        "MSTR provider event already exists with "
                        "different immutable state"
                    )
                session.rollback()
                return StoredMstrBtcHoldingsState(
                    row_id=int(existing["id"]),
                    created=False,
                )
        except MstrBtcHoldingsStoreError:
            raise
        except Exception as exc:
            raise MstrBtcHoldingsStoreError(
                "Failed to record MSTR holdings state: "
                f"{type(exc).__name__}"
            ) from None

    def pin_baseline(
        self,
        *,
        before: datetime,
    ) -> MstrBtcHoldingsBaseline:
        boundary = _as_utc(before, "before")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                row = session.execute(
                    text_factory(_PIN_BASELINE_SQL),
                    {"before": boundary},
                ).mappings().one_or_none()
        except Exception as exc:
            raise MstrBtcHoldingsStoreError(
                "Failed to pin MSTR holdings baseline: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            raise MstrBtcBaselineNotFound(
                "No validated MSTR holdings state exists before window"
            )
        return _baseline_from_row(row)

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
                raise MstrBtcHoldingsStoreError(
                    "MSTR holdings database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise MstrBtcHoldingsStoreError(
                    "MSTR holdings require SQLAlchemy "
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
                raise MstrBtcHoldingsStoreError(
                    "Failed to initialize MSTR holdings database: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise MstrBtcHoldingsStoreError(
                    "MSTR holdings require SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _observation_params(
    observation: MstrBtcHoldingsObservation,
) -> dict[str, Any]:
    return {
        "holdings_btc": observation.holdings_btc,
        "as_of": observation.as_of,
        "observed_at": observation.observed_at,
        "provider": observation.provider.value,
        "provider_event_id": observation.provider_event_id,
        "source_url": observation.source_url,
        "document_fingerprint": observation.document_fingerprint,
        "predecessor_state_id": observation.predecessor_state_id,
        "validation_status": observation.validation_status.value,
        "attributes": _json_dumps(observation.attributes),
    }


def _observation_matches_row(
    observation: MstrBtcHoldingsObservation,
    row: Mapping[str, Any],
) -> bool:
    return (
        int(row["holdings_btc"]) == observation.holdings_btc
        and _as_utc(row["as_of"], "stored as_of") == observation.as_of
        and _as_utc(
            row["observed_at"],
            "stored observed_at",
        ) == observation.observed_at
        and str(row["provider"]) == observation.provider.value
        and str(row["provider_event_id"])
        == observation.provider_event_id
        and str(row["source_url"]) == observation.source_url
        and str(row["document_fingerprint"])
        == observation.document_fingerprint
        and _optional_int(row.get("predecessor_state_id"))
        == observation.predecessor_state_id
        and str(row["validation_status"])
        == observation.validation_status.value
        and _json_mapping(row.get("attributes"))
        == dict(observation.attributes)
    )


def _baseline_from_row(row: Mapping[str, Any]) -> MstrBtcHoldingsBaseline:
    try:
        provider = MstrBtcProvider(str(row["provider"]))
    except ValueError:
        raise MstrBtcHoldingsStoreError(
            "Stored MSTR holdings provider is unsupported"
        ) from None
    return MstrBtcHoldingsBaseline(
        state_id=str(row["id"]),
        holdings_btc=int(row["holdings_btc"]),
        as_of=row["as_of"],
        provider=provider,
        provider_event_id=str(row["provider_event_id"]),
        source_url=str(row["source_url"]),
    )


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
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise MstrBtcHoldingsStoreError(
            "Stored MSTR holdings attributes must be a JSON object"
        )
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
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        f"unsupported JSON value type: {type(value).__name__}"
    )


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_int(value: object | None) -> int | None:
    return None if value is None else int(value)


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
