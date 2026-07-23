from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


_VALID_ROLES = {"primary", "analytics"}
_VALID_TARGETS = {"local", "server_int", "server_ext"}


@dataclass(frozen=True)
class DatabaseSelection:
    role: str
    target: str
    source: str
    url: str | None = field(default=None, repr=False)
    error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.url)


def resolve_database_selection(
    role: str,
    environ: Mapping[str, str] | None = None,
) -> DatabaseSelection:
    env = environ if environ is not None else os.environ
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in _VALID_ROLES:
        return DatabaseSelection(
            role=normalized_role or "unknown",
            target="invalid",
            source="role",
            error=f"Unknown database role: {normalized_role!r}",
        )

    direct_names = (
        ("CBR_DATABASE_URL", "DATABASE_URL")
        if normalized_role == "primary"
        else (
            "CBR_ANALYTICS_DATABASE_URL",
            "ANALYTICS_DATABASE_URL",
        )
    )
    for name in direct_names:
        direct_url = _clean(env.get(name))
        if direct_url:
            return DatabaseSelection(
                role=normalized_role,
                target="url",
                source=name,
                url=direct_url,
            )

    try:
        on_render = _resolve_on_render(env)
    except ValueError as exc:
        return DatabaseSelection(
            role=normalized_role,
            target="invalid",
            source="environment",
            error=str(exc),
        )
    default_target = "server_int" if on_render else "server_ext"
    if normalized_role == "primary":
        target_name = (
            _clean(env.get("CBR_PRIMARY_DB_TARGET"))
            or _clean(env.get("PRIMARY_DB_TARGET"))
            or _clean(env.get("DB_TARGET"))
        )
        url_names = {
            "local": "DATABASE_URL_LOCAL",
            "server_int": "DATABASE_URL_SERVER_INT",
            "server_ext": "DATABASE_URL_SERVER_EXT",
        }
    else:
        target_name = (
            _clean(env.get("CBR_ANALYTICS_DB_TARGET"))
            or _clean(env.get("ANALYTICS_DB_TARGET"))
        )
        url_names = {
            "local": "ANALYTICS_DATABASE_URL_LOCAL",
            "server_int": "ANALYTICS_DATABASE_URL_SERVER_INT",
            "server_ext": "ANALYTICS_DATABASE_URL_SERVER_EXT",
        }

    target = (target_name or default_target).lower()
    if target not in _VALID_TARGETS:
        return DatabaseSelection(
            role=normalized_role,
            target=target,
            source="target",
            error=(
                f"Invalid {normalized_role} database target: "
                f"{target!r}"
            ),
        )

    source = url_names[target]
    url = _clean(env.get(source)) or None
    error = None
    if url is None:
        error = (
            f"{source} is not configured for "
            f"role={normalized_role} target={target}"
        )
    return DatabaseSelection(
        role=normalized_role,
        target=target,
        source=source,
        url=url,
        error=error,
    )


def resolve_admin_database_selection(
    environ: Mapping[str, str] | None = None,
) -> DatabaseSelection:
    env = environ if environ is not None else os.environ
    admin_url = _clean(env.get("CBR_ADMIN_DATABASE_URL"))
    if admin_url:
        return DatabaseSelection(
            role="primary",
            target="admin_url",
            source="CBR_ADMIN_DATABASE_URL",
            url=admin_url,
        )
    return resolve_database_selection("primary", env)


def _resolve_on_render(env: Mapping[str, str]) -> bool:
    explicit = _clean(env.get("CBR_ON_RENDER"))
    if explicit:
        return _parse_bool(explicit, name="CBR_ON_RENDER")
    legacy = _clean(env.get("SERVER"))
    if legacy:
        return _parse_bool(legacy, name="SERVER")
    return False


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = _clean(value).lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
