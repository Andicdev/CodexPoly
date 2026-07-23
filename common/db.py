from __future__ import annotations

import os
from threading import RLock
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from common import config
from common.base import Base


_ENGINES: dict[str, Any] = {}
_SESSIONS: dict[str, "_LazySessionFactory"] = {}
_SESSIONMAKERS: dict[str, Any] = {}
_LOCK = RLock()

_KEEPALIVES = {
    "keepalives": 1,
    "keepalives_idle": int(os.getenv("DB_KEEPALIVES_IDLE", "30")),
    "keepalives_interval": int(os.getenv("DB_KEEPALIVES_INTERVAL", "10")),
    "keepalives_count": int(os.getenv("DB_KEEPALIVES_COUNT", "5")),
}

_ENGINE_KW = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 5,
    "max_overflow": 10,
    "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    "pool_use_lifo": True,
    "pool_reset_on_return": "rollback",
    "connect_args": _KEEPALIVES,
    "hide_parameters": True,
    "echo": False,
}


def get_engine(role: str = "primary"):
    """Return a cached engine without opening a database connection."""
    with _LOCK:
        if role not in _ENGINES:
            url = config.resolve_db_url(role)
            _ENGINES[role] = create_engine(url, **_ENGINE_KW)
        return _ENGINES[role]


def _get_sessionmaker(role: str):
    with _LOCK:
        if role not in _SESSIONMAKERS:
            _SESSIONMAKERS[role] = sessionmaker(
                bind=get_engine(role),
                expire_on_commit=False,
            )
        return _SESSIONMAKERS[role]


class _LazySessionFactory:
    """Resolve DB configuration only when a Session is actually opened."""

    def __init__(self, role: str):
        self.role = role

    def __call__(self, *args: Any, **kwargs: Any):
        return _get_sessionmaker(self.role)(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(_get_sessionmaker(self.role), name)

    def __repr__(self) -> str:
        return f"<LazySessionFactory role={self.role!r}>"


class _LazyEngine:
    """Compatibility proxy for legacy imports of ``common.db.engine``."""

    def __init__(self, role: str):
        self.role = role

    def __getattr__(self, name: str):
        return getattr(get_engine(self.role), name)

    def __repr__(self) -> str:
        return f"<LazyEngine role={self.role!r}>"


def get_session(role: str = "primary"):
    """Return a cached lazy Session factory for the requested role."""
    with _LOCK:
        if role not in _SESSIONS:
            _SESSIONS[role] = _LazySessionFactory(role)
        return _SESSIONS[role]


def create_schema(role: str = "primary") -> None:
    """Create known tables explicitly; this is never called on import."""
    Base.metadata.create_all(get_engine(role))


def dispose_all() -> None:
    """Dispose cached engines during tests or controlled shutdown."""
    with _LOCK:
        engines = list(_ENGINES.values())
        _ENGINES.clear()
        _SESSIONMAKERS.clear()
    for cached_engine in engines:
        cached_engine.dispose()


# Backwards-compatible names. Both remain inert until actually used.
engine = _LazyEngine("primary")
Session = get_session("primary")
