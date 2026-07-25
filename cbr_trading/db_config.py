from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import quote

from cbr_trading.runtime_secrets import read_runtime_secret


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
        direct_url = _clean(
            read_runtime_secret(name, environ=env)
        )
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
    url = _clean(
        read_runtime_secret(source, environ=env)
    ) or None
    if url is None and target == "server_int":
        component_url = build_internal_database_url(
            normalized_role,
            env,
        )
        if component_url:
            url = component_url
            source = (
                "DATABASE_APP_PASSWORD"
                if normalized_role == "primary"
                else "ANALYTICS_DATABASE_PASSWORD"
            )
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
    admin_url = _clean(
        read_runtime_secret(
            "CBR_ADMIN_DATABASE_URL",
            environ=env,
        )
    )
    if admin_url:
        return DatabaseSelection(
            role="primary",
            target="admin_url",
            source="CBR_ADMIN_DATABASE_URL",
            url=admin_url,
        )
    internal_admin_url = _build_database_url(
        env,
        password_name="POSTGRES_PASSWORD",
        host_name="DATABASE_HOST",
        port_name="DATABASE_PORT",
        database_name="DATABASE_NAME",
        user_name="POSTGRES_USER",
        default_host="postgres",
        default_database="codexpoly",
        default_user="codexpoly_admin",
    )
    if internal_admin_url:
        return DatabaseSelection(
            role="primary",
            target="admin_internal",
            source="POSTGRES_PASSWORD",
            url=internal_admin_url,
        )
    return resolve_database_selection("primary", env)


def build_internal_database_url(
    role: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = environ if environ is not None else os.environ
    normalized_role = str(role or "").strip().lower()
    if normalized_role == "primary":
        return _build_database_url(
            env,
            password_name="DATABASE_APP_PASSWORD",
            host_name="DATABASE_HOST",
            port_name="DATABASE_PORT",
            database_name="DATABASE_NAME",
            user_name="DATABASE_USER",
            default_host="postgres",
            default_database="codexpoly",
            default_user="codexpoly_app",
        )
    if normalized_role == "analytics":
        return _build_database_url(
            env,
            password_name="ANALYTICS_DATABASE_PASSWORD",
            host_name="ANALYTICS_DATABASE_HOST",
            port_name="ANALYTICS_DATABASE_PORT",
            database_name="ANALYTICS_DATABASE_NAME",
            user_name="ANALYTICS_DATABASE_USER",
            default_host="analytics-postgres",
            default_database="codexpoly_analytics",
            default_user="codexpoly_analytics",
        )
    raise ValueError(f"Unknown database role: {normalized_role!r}")


def _build_database_url(
    env: Mapping[str, str],
    *,
    password_name: str,
    host_name: str,
    port_name: str,
    database_name: str,
    user_name: str,
    default_host: str,
    default_database: str,
    default_user: str,
) -> str | None:
    password = read_runtime_secret(password_name, environ=env)
    if password is None:
        return None

    host = _clean(env.get(host_name)) or default_host
    port_text = _clean(env.get(port_name)) or "5432"
    database = _clean(env.get(database_name)) or default_database
    user = _clean(env.get(user_name)) or default_user
    if not host.replace(".", "").replace("-", "").isalnum():
        raise ValueError(f"{host_name} contains unsupported characters")
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError(f"{port_name} must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{port_name} must be between 1 and 65535")
    if not str(password):
        return None
    return (
        f"postgresql://{quote(user, safe='')}:"
        f"{quote(str(password), safe='')}@"
        f"{host}:{port}/{quote(database, safe='')}"
    )


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
