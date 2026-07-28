from __future__ import annotations

import re
from typing import Any, Callable


_APPLICATION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class SharedSqlAlchemyRuntime:
    """Own one bounded SQLAlchemy engine for all stores in one process."""

    def __init__(
        self,
        *,
        database_url: str,
        application_name: str,
        pool_size: int,
        max_overflow: int,
        pool_timeout: float = 5.0,
    ) -> None:
        url = str(database_url or "").strip()
        name = str(application_name or "").strip().lower()
        if not url:
            raise ValueError("database_url is required")
        if not _APPLICATION_NAME_RE.fullmatch(name):
            raise ValueError("application_name is invalid")
        if pool_size < 1:
            raise ValueError("pool_size must be positive")
        if max_overflow < 0:
            raise ValueError("max_overflow cannot be negative")
        if pool_timeout <= 0:
            raise ValueError("pool_timeout must be positive")

        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
        except ImportError as exc:
            raise RuntimeError(
                "Shared database runtime requires SQLAlchemy"
            ) from exc

        connect_args: dict[str, object] = {}
        normalized_url = _normalize_database_url(url)
        if normalized_url.startswith(
            ("postgresql://", "postgresql+psycopg2://")
        ):
            connect_args["application_name"] = name
        try:
            self._engine = create_engine(
                normalized_url,
                pool_size=int(pool_size),
                max_overflow=int(max_overflow),
                pool_timeout=float(pool_timeout),
                pool_pre_ping=True,
                pool_recycle=300,
                pool_reset_on_return="rollback",
                hide_parameters=True,
                connect_args=connect_args,
            )
            self._session_factory: Callable[[], Any] = sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize shared database runtime: "
                f"{type(exc).__name__}"
            ) from exc
        self._closed = False

    @property
    def session_factory(self) -> Callable[[], Any]:
        if self._closed:
            raise RuntimeError("shared database runtime is closed")
        return self._session_factory

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._engine.dispose()


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
