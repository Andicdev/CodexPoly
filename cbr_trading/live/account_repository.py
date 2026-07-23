from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


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


class TradingAccountLoadError(RuntimeError):
    """Safe error raised when a trading account cannot be loaded."""


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
