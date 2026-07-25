from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from cbr_trading.runtime_secrets import read_runtime_secret


_SET_READ_ONLY_SQL = "SET TRANSACTION READ ONLY"
_SELECT_ACCOUNT_SQL = """
SELECT
    name,
    wallet_address,
    venue,
    is_active,
    pk_enc,
    signature_type
FROM trading_accounts
WHERE lower(name) = lower(:account_name)
ORDER BY name
""".strip()

_SELECT_ACCOUNT_METADATA_SQL = """
SELECT
    account_name AS name,
    wallet_address,
    venue,
    is_active,
    signature_type
FROM trading_account_metadata
WHERE lower(account_name) = lower(:account_name)
ORDER BY account_name
""".strip()


class TradingAccountLoadError(RuntimeError):
    """Safe error raised when a trading account cannot be loaded."""


class TradingAccountRepository(Protocol):
    def load_active(self, account_name: str) -> "TradingAccountRecord":
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class TradingAccountRecord:
    name: str
    wallet_address: str
    venue: str
    is_active: bool
    signature_type: int
    encrypted_private_key: bytes = field(repr=False)

    @property
    def wallet_masked(self) -> str:
        if len(self.wallet_address) < 12:
            return "<invalid>"
        return (
            f"{self.wallet_address[:6]}..."
            f"{self.wallet_address[-4:]}"
        )


class SqlAlchemyTradingAccountRepository:
    """Read one account through a transaction forced to READ ONLY."""

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

    def load_active(self, account_name: str) -> TradingAccountRecord:
        requested = str(account_name or "").strip()
        if not requested:
            raise TradingAccountLoadError("Trading account name is empty")

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                result = session.execute(
                    text_factory(_SELECT_ACCOUNT_SQL),
                    {"account_name": requested},
                )
                rows = result.mappings().all()
        except TradingAccountLoadError:
            raise
        except Exception as exc:
            raise TradingAccountLoadError(
                "Failed to load trading account from database: "
                f"{type(exc).__name__}"
            ) from exc

        return normalize_account_rows(rows, requested=requested)

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory

        if session_factory is None:
            if not self._database_url:
                raise TradingAccountLoadError(
                    "Trading database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise TradingAccountLoadError(
                    "Account loading requires SQLAlchemy and a "
                    "PostgreSQL driver"
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
                raise TradingAccountLoadError(
                    "Failed to initialize account database connection: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory

        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise TradingAccountLoadError(
                    "Account loading requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory

        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


class RuntimeSecretTradingAccountRepository:
    """Load one configured account without a trading_accounts row."""

    def __init__(self, account: TradingAccountRecord):
        self._account = account

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeSecretTradingAccountRepository":
        env = environ if environ is not None else os.environ
        name = _clean(env.get("TRADING_ACCOUNT_NAME"))
        if not name:
            raise TradingAccountLoadError(
                "Configured trading account name is empty"
            )
        wallet = _clean(env.get("TRADING_ACCOUNT_WALLET_ADDRESS"))
        venue = (
            _clean(env.get("TRADING_ACCOUNT_VENUE"))
            or "polymarket_clob"
        )
        signature_type = _clean(
            env.get("TRADING_ACCOUNT_SIGNATURE_TYPE")
        )
        encrypted_key = read_runtime_secret(
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            environ=env,
        )
        account = normalize_account_rows(
            [
                {
                    "name": name,
                    "wallet_address": wallet,
                    "venue": venue,
                    "is_active": True,
                    "pk_enc": (
                        str(encrypted_key).encode("utf-8")
                        if encrypted_key is not None
                        else None
                    ),
                    "signature_type": signature_type,
                }
            ],
            requested=name,
        )
        return cls(account)

    def load_active(self, account_name: str) -> TradingAccountRecord:
        requested = _clean(account_name)
        if not requested:
            raise TradingAccountLoadError("Trading account name is empty")
        if requested.casefold() != self._account.name.casefold():
            raise TradingAccountLoadError(
                f"Trading account not found: {requested!r}"
            )
        return self._account

    def close(self) -> None:
        return None


class SqlAlchemyRuntimeSecretTradingAccountRepository:
    """Combine public database metadata with one encrypted file-secret."""

    def __init__(
        self,
        *,
        database_url: str,
        configured_name: str,
        encrypted_private_key: bytes,
        session_factory: Callable[[], Any] | None = None,
        text_factory: Callable[[str], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._configured_name = _clean(configured_name)
        self._encrypted_private_key = bytes(encrypted_private_key)
        self._session_factory = session_factory
        self._text_factory = text_factory
        self._engine: Any | None = None

    @classmethod
    def from_env(
        cls,
        *,
        database_url: str,
        environ: Mapping[str, str] | None = None,
    ) -> "SqlAlchemyRuntimeSecretTradingAccountRepository":
        env = environ if environ is not None else os.environ
        normalized_database_url = str(database_url or "").strip()
        if not normalized_database_url:
            raise TradingAccountLoadError(
                "Trading metadata database URL is not configured"
            )
        name = _clean(env.get("TRADING_ACCOUNT_NAME"))
        if not name:
            raise TradingAccountLoadError(
                "Configured trading account name is empty"
            )
        encrypted_key = read_runtime_secret(
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            environ=env,
        )
        if encrypted_key is None:
            raise TradingAccountLoadError(
                f"Trading account has no encrypted private key: {name!r}"
            )
        return cls(
            database_url=normalized_database_url,
            configured_name=name,
            encrypted_private_key=str(encrypted_key).encode("utf-8"),
        )

    def load_active(self, account_name: str) -> TradingAccountRecord:
        requested = _clean(account_name)
        if not requested:
            raise TradingAccountLoadError("Trading account name is empty")
        if requested.casefold() != self._configured_name.casefold():
            raise TradingAccountLoadError(
                f"Trading account not found: {requested!r}"
            )

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                result = session.execute(
                    text_factory(_SELECT_ACCOUNT_METADATA_SQL),
                    {"account_name": self._configured_name},
                )
                metadata_rows = result.mappings().all()
        except TradingAccountLoadError:
            raise
        except Exception as exc:
            raise TradingAccountLoadError(
                "Failed to load trading account metadata: "
                f"{type(exc).__name__}"
            ) from exc

        rows = [
            {
                **dict(row),
                "pk_enc": self._encrypted_private_key,
            }
            for row in metadata_rows
        ]
        return normalize_account_rows(
            rows,
            requested=self._configured_name,
        )

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise TradingAccountLoadError(
                    "Account loading requires SQLAlchemy and a "
                    "PostgreSQL driver"
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
                raise TradingAccountLoadError(
                    "Failed to initialize account database connection: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise TradingAccountLoadError(
                    "Account loading requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def build_trading_account_repository(
    *,
    database_url: str = "",
    environ: Mapping[str, str] | None = None,
) -> TradingAccountRepository:
    """Select the legacy database or single-secret account provider."""

    env = environ if environ is not None else os.environ
    source = (
        _clean(env.get("TRADING_ACCOUNT_SOURCE"))
        or "database"
    ).lower()
    if source == "database":
        return SqlAlchemyTradingAccountRepository(
            database_url=database_url
        )
    if source == "single_secret":
        return RuntimeSecretTradingAccountRepository.from_env(env)
    if source == "database_metadata_secret":
        return SqlAlchemyRuntimeSecretTradingAccountRepository.from_env(
            database_url=database_url,
            environ=env,
        )
    raise TradingAccountLoadError(
        f"Unsupported trading account source: {source!r}"
    )


def normalize_account_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    requested: str,
) -> TradingAccountRecord:
    if not rows:
        raise TradingAccountLoadError(
            f"Trading account not found: {requested!r}"
        )
    if len(rows) != 1:
        raise TradingAccountLoadError(
            "Multiple trading accounts match the name "
            f"case-insensitively: {requested!r}"
        )

    row = rows[0]
    name = str(row.get("name") or "").strip()
    wallet = str(row.get("wallet_address") or "").strip()
    venue = str(row.get("venue") or "").strip()
    encrypted_key = row.get("pk_enc")

    if row.get("is_active") is not True:
        raise TradingAccountLoadError(
            f"Trading account is inactive: {name or requested!r}"
        )
    if venue != "polymarket_clob":
        raise TradingAccountLoadError(
            f"Unsupported trading venue for account {name!r}: {venue!r}"
        )
    if not wallet:
        raise TradingAccountLoadError(
            f"Trading account has no wallet: {name!r}"
        )
    if not isinstance(
        encrypted_key,
        (bytes, bytearray, memoryview),
    ) or not encrypted_key:
        raise TradingAccountLoadError(
            f"Trading account has no encrypted private key: {name!r}"
        )

    try:
        signature_type = int(row.get("signature_type"))
    except (TypeError, ValueError) as exc:
        raise TradingAccountLoadError(
            f"Trading account has an invalid signature type: {name!r}"
        ) from exc

    if signature_type not in {0, 1, 2, 3}:
        raise TradingAccountLoadError(
            f"Unsupported signature type for account {name!r}: "
            f"{signature_type}"
        )

    return TradingAccountRecord(
        name=name,
        wallet_address=wallet,
        venue=venue,
        is_active=True,
        signature_type=signature_type,
        encrypted_private_key=bytes(encrypted_key),
    )


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _clean(value: object | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
