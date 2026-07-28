from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    RepriceOnTickChange,
)
from cbr_trading.orchestration.contracts import (
    ResolutionExecutionProfile,
    ResolutionProfileTemplate,
)


_MIGRATION_PATHS = tuple(
    Path(__file__).resolve().parents[1]
    / "migrations"
    / name
    for name in (
        "005_add_resolution_execution_profiles.sql",
        "006_add_resolution_profile_templates.sql",
        "015_set_default_resolution_profile_quantity_100.sql",
    )
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_execution_profiles') IS NOT NULL
        AS profiles_table,
    (
        SELECT count(*) = 20
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_execution_profiles'
    ) AS profiles_columns,
    to_regclass('resolution_profile_templates') IS NOT NULL
        AS templates_table,
    (
        SELECT count(*) = 12
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_profile_templates'
    ) AS templates_columns,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_resolution_execution_profiles_key'
        )
          AND indisunique
    ) AS profile_key_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_resolution_execution_profiles_scope'
        )
          AND indisunique
    ) AS profile_scope_index,
    EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_resolution_profile_templates_key'
        )
          AND indisunique
    ) AS template_key_index
""".strip()

_UPSERT_SQL = """
INSERT INTO resolution_execution_profiles (
    profile_key,
    scope_id,
    source_name,
    source_reference,
    account_name,
    condition_id,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    prepare_from,
    expires_at,
    metadata,
    status
)
VALUES (
    :profile_key,
    :scope_id,
    :source_name,
    :source_reference,
    :account_name,
    :condition_id,
    :yes_desired_price,
    :no_desired_price,
    :quantity,
    :lifecycle_kind,
    :old_tick,
    :new_tick,
    :max_reprices,
    :prepare_from,
    :expires_at,
    CAST(:metadata AS jsonb),
    :status
)
ON CONFLICT (profile_key) DO UPDATE
SET
    scope_id = EXCLUDED.scope_id,
    source_name = EXCLUDED.source_name,
    source_reference = EXCLUDED.source_reference,
    account_name = EXCLUDED.account_name,
    condition_id = EXCLUDED.condition_id,
    yes_desired_price = EXCLUDED.yes_desired_price,
    no_desired_price = EXCLUDED.no_desired_price,
    quantity = EXCLUDED.quantity,
    lifecycle_kind = EXCLUDED.lifecycle_kind,
    old_tick = EXCLUDED.old_tick,
    new_tick = EXCLUDED.new_tick,
    max_reprices = EXCLUDED.max_reprices,
    prepare_from = EXCLUDED.prepare_from,
    expires_at = EXCLUDED.expires_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_execution_profiles.status = 'DISABLED'
RETURNING id
""".strip()

_LOAD_ENABLED_SQL = """
SELECT
    profile_key,
    scope_id,
    source_name,
    source_reference,
    account_name,
    condition_id,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    prepare_from,
    expires_at,
    metadata
FROM resolution_execution_profiles
WHERE status = 'ENABLED'
  AND prepare_from <= now()
  AND expires_at >= now()
  AND (
      CAST(:source_name AS text) IS NULL
      OR lower(source_name) = lower(CAST(:source_name AS text))
  )
ORDER BY source_name, scope_id, id
""".strip()

_LOAD_BY_KEY_SQL = """
SELECT
    profile_key,
    scope_id,
    source_name,
    source_reference,
    account_name,
    condition_id,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    prepare_from,
    expires_at,
    metadata
FROM resolution_execution_profiles
WHERE profile_key = :profile_key
""".strip()

_SET_STATUS_SQL = """
UPDATE resolution_execution_profiles
SET status = :status, updated_at = now()
WHERE profile_key = :profile_key
RETURNING id
""".strip()

_LOAD_TEMPLATE_SQL = """
SELECT
    template_key,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    metadata
FROM resolution_profile_templates
WHERE template_key = :template_key
""".strip()

_UPSERT_TEMPLATE_SQL = """
INSERT INTO resolution_profile_templates (
    template_key,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    metadata
)
VALUES (
    :template_key,
    :yes_desired_price,
    :no_desired_price,
    :quantity,
    :lifecycle_kind,
    :old_tick,
    :new_tick,
    :max_reprices,
    CAST(:metadata AS jsonb)
)
ON CONFLICT (template_key) DO UPDATE
SET
    yes_desired_price = EXCLUDED.yes_desired_price,
    no_desired_price = EXCLUDED.no_desired_price,
    quantity = EXCLUDED.quantity,
    lifecycle_kind = EXCLUDED.lifecycle_kind,
    old_tick = EXCLUDED.old_tick,
    new_tick = EXCLUDED.new_tick,
    max_reprices = EXCLUDED.max_reprices,
    metadata = EXCLUDED.metadata,
    updated_at = now()
RETURNING id
""".strip()


class ResolutionProfileStoreError(RuntimeError):
    """Sanitized persistence failure for execution profiles."""


@dataclass(frozen=True)
class StoredResolutionProfile:
    row_id: int


class SqlAlchemyResolutionProfileStore:
    """Explicit migration and source-neutral execution configuration."""

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
            raise ResolutionProfileStoreError(
                "Failed to apply additive resolution profile migration: "
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
            raise ResolutionProfileStoreError(
                "Failed to verify resolution profile schema: "
                f"{type(exc).__name__}"
            ) from None
        if not all(
            bool(row.get(name))
            for name in (
                "profiles_table",
                "profiles_columns",
                "templates_table",
                "templates_columns",
                "profile_key_index",
                "profile_scope_index",
                "template_key_index",
            )
        ):
            raise ResolutionProfileStoreError(
                "Resolution profile schema is not ready"
            )

    def load_template(
        self,
        template_key: str = "default",
    ) -> ResolutionProfileTemplate:
        normalized_key = str(template_key or "").strip()
        if not normalized_key:
            raise ValueError("template_key is required")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_LOAD_TEMPLATE_SQL),
                    {"template_key": normalized_key},
                ).mappings().one_or_none()
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to load resolution profile template: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            raise ResolutionProfileStoreError(
                "Resolution profile template does not exist"
            )
        return _template_from_row(row)

    def save_template(
        self,
        template: ResolutionProfileTemplate,
    ) -> StoredResolutionProfile:
        params = _template_params(template)
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_UPSERT_TEMPLATE_SQL),
                    params,
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to save resolution profile template: "
                f"{type(exc).__name__}"
            ) from None
        return StoredResolutionProfile(row_id=int(row["id"]))

    def save(
        self,
        profile: ResolutionExecutionProfile,
    ) -> StoredResolutionProfile:
        params = _profile_params(
            profile,
            status="DISABLED",
        )
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_UPSERT_SQL),
                    params,
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to save resolution execution profile: "
                f"{type(exc).__name__}"
            ) from None
        return StoredResolutionProfile(row_id=int(row["id"]))

    def set_enabled(
        self,
        profile_key: str,
        *,
        enabled: bool,
    ) -> StoredResolutionProfile:
        normalized_key = str(profile_key or "").strip()
        if not normalized_key:
            raise ValueError("profile_key is required")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SET_STATUS_SQL),
                    {
                        "profile_key": normalized_key,
                        "status": (
                            "ENABLED" if enabled else "DISABLED"
                        ),
                    },
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    raise ResolutionProfileStoreError(
                        "Resolution execution profile does not exist"
                    )
                session.commit()
        except ResolutionProfileStoreError:
            raise
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to update resolution execution profile: "
                f"{type(exc).__name__}"
            ) from None
        return StoredResolutionProfile(row_id=int(row["id"]))

    def load_enabled(
        self,
        *,
        source_name: str | None = None,
    ) -> tuple[ResolutionExecutionProfile, ...]:
        normalized_source = str(source_name or "").strip() or None
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                rows = session.execute(
                    text_factory(_LOAD_ENABLED_SQL),
                    {"source_name": normalized_source},
                ).mappings().all()
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to load resolution execution profiles: "
                f"{type(exc).__name__}"
            ) from None
        return tuple(_profile_from_row(row) for row in rows)

    def load(
        self,
        profile_key: str,
    ) -> ResolutionExecutionProfile:
        normalized_key = str(profile_key or "").strip()
        if not normalized_key:
            raise ValueError("profile_key is required")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_LOAD_BY_KEY_SQL),
                    {"profile_key": normalized_key},
                ).mappings().one_or_none()
        except Exception as exc:
            raise ResolutionProfileStoreError(
                "Failed to load resolution execution profile: "
                f"{type(exc).__name__}"
            ) from None
        if row is None:
            raise ResolutionProfileStoreError(
                "Resolution execution profile does not exist"
            )
        return _profile_from_row(row)

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
                raise ResolutionProfileStoreError(
                    "Resolution profile database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise ResolutionProfileStoreError(
                    "Resolution profiles require SQLAlchemy "
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
                raise ResolutionProfileStoreError(
                    "Failed to initialize resolution profile database: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise ResolutionProfileStoreError(
                    "Resolution profiles require SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _profile_params(
    profile: ResolutionExecutionProfile,
    *,
    status: str,
) -> dict[str, Any]:
    policy = profile.lifecycle_policy
    if isinstance(policy, RepriceOnTickChange):
        lifecycle_kind = policy.kind
        old_tick: Decimal | None = policy.old_tick
        new_tick: Decimal | None = policy.new_tick
        max_reprices: int | None = policy.max_reprices
    else:
        lifecycle_kind = policy.kind
        old_tick = None
        new_tick = None
        max_reprices = None
    return {
        "profile_key": profile.profile_key,
        "scope_id": profile.scope_id,
        "source_name": profile.source_name,
        "source_reference": profile.source_reference,
        "account_name": profile.account_name,
        "condition_id": profile.condition_id,
        "yes_desired_price": profile.yes_desired_price,
        "no_desired_price": profile.no_desired_price,
        "quantity": profile.quantity,
        "lifecycle_kind": lifecycle_kind,
        "old_tick": old_tick,
        "new_tick": new_tick,
        "max_reprices": max_reprices,
        "prepare_from": profile.prepare_from,
        "expires_at": profile.expires_at,
        "metadata": _json_dumps(profile.metadata),
        "status": status,
    }


def _template_params(
    template: ResolutionProfileTemplate,
) -> dict[str, Any]:
    policy = template.lifecycle_policy
    if isinstance(policy, RepriceOnTickChange):
        lifecycle_kind = policy.kind
        old_tick: Decimal | None = policy.old_tick
        new_tick: Decimal | None = policy.new_tick
        max_reprices: int | None = policy.max_reprices
    else:
        lifecycle_kind = policy.kind
        old_tick = None
        new_tick = None
        max_reprices = None
    return {
        "template_key": template.template_key,
        "yes_desired_price": template.yes_desired_price,
        "no_desired_price": template.no_desired_price,
        "quantity": template.quantity,
        "lifecycle_kind": lifecycle_kind,
        "old_tick": old_tick,
        "new_tick": new_tick,
        "max_reprices": max_reprices,
        "metadata": _json_dumps(template.metadata),
    }


def _profile_from_row(row: Mapping[str, Any]) -> ResolutionExecutionProfile:
    kind = str(row["lifecycle_kind"])
    if kind == "keep_open":
        policy = KeepOpenPolicy()
    elif kind == "reprice_on_tick_change":
        policy = RepriceOnTickChange(
            old_tick=Decimal(str(row["old_tick"])),
            new_tick=Decimal(str(row["new_tick"])),
            max_reprices=int(row["max_reprices"]),
        )
    else:
        raise ResolutionProfileStoreError(
            "Stored resolution profile has unsupported lifecycle policy"
        )
    return ResolutionExecutionProfile(
        profile_key=str(row["profile_key"]),
        scope_id=str(row["scope_id"]),
        source_name=str(row["source_name"]),
        source_reference=str(row["source_reference"]),
        account_name=str(row["account_name"]),
        condition_id=str(row["condition_id"]),
        yes_desired_price=Decimal(str(row["yes_desired_price"])),
        no_desired_price=Decimal(str(row["no_desired_price"])),
        quantity=Decimal(str(row["quantity"])),
        prepare_from=row["prepare_from"],
        expires_at=row["expires_at"],
        lifecycle_policy=policy,
        metadata=_json_mapping(row.get("metadata")),
    )


def _template_from_row(
    row: Mapping[str, Any],
) -> ResolutionProfileTemplate:
    return ResolutionProfileTemplate(
        template_key=str(row["template_key"]),
        yes_desired_price=Decimal(str(row["yes_desired_price"])),
        no_desired_price=Decimal(str(row["no_desired_price"])),
        quantity=Decimal(str(row["quantity"])),
        lifecycle_policy=_lifecycle_policy_from_row(row),
        metadata=_json_mapping(row.get("metadata")),
    )


def _lifecycle_policy_from_row(
    row: Mapping[str, Any],
) -> KeepOpenPolicy | RepriceOnTickChange:
    kind = str(row["lifecycle_kind"])
    if kind == "keep_open":
        return KeepOpenPolicy()
    if kind == "reprice_on_tick_change":
        return RepriceOnTickChange(
            old_tick=Decimal(str(row["old_tick"])),
            new_tick=Decimal(str(row["new_tick"])),
            max_reprices=int(row["max_reprices"]),
        )
    raise ResolutionProfileStoreError(
        "Stored resolution profile has unsupported lifecycle policy"
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
        raise ResolutionProfileStoreError(
            "Stored resolution profile metadata must be a JSON object"
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
    if isinstance(value, Decimal):
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
