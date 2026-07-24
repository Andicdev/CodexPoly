from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence


CBR_TICKER = "CBR"
CBR_CHANGE_METRIC = "cbr_key_rate_change_bp"
CBR_EXECUTION_PATH = "fast"

_SET_READ_ONLY_SQL = "SET TRANSACTION READ ONLY"
_SELECT_RULES_SQL = """
SELECT
    id,
    type,
    ticker,
    rule_key,
    status,
    priority,
    params,
    tg_chat_id,
    account_name,
    condition_id,
    question,
    order_qty,
    order_price
FROM monitored_news
WHERE status = :status
  AND ticker = :ticker
  AND params ->> 'metric_key' = :metric_key
  AND COALESCE(params ->> 'execution_path', 'poll') = :execution_path
ORDER BY priority ASC, id ASC
""".strip()

_SELECT_ACTIVE_RULE_BY_ID_SQL = """
SELECT
    id,
    type,
    ticker,
    rule_key,
    status,
    priority,
    params,
    tg_chat_id,
    account_name,
    condition_id,
    question,
    order_qty,
    order_price
FROM monitored_news
WHERE id = :rule_id
  AND status = :status
""".strip()


class RuleLoadError(RuntimeError):
    """Safe error raised when active rules cannot be loaded."""


class RuleRepository(Protocol):
    def load_active_cbr_rules(self) -> list[dict[str, Any]]: ...

    def load_active_rule(self, rule_id: int) -> dict[str, Any]: ...


class SqlAlchemyRuleRepository:
    """Read active CBR rules through a transaction forced to READ ONLY."""

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

    def __repr__(self) -> str:
        return (
            "<SqlAlchemyRuleRepository "
            f"configured={bool(self._database_url)!r}>"
        )

    def load_active_cbr_rules(self) -> list[dict[str, Any]]:
        session_factory, text_factory = self._resolve_dependencies()
        params = {
            "status": "active",
            "ticker": CBR_TICKER,
            "metric_key": CBR_CHANGE_METRIC,
            "execution_path": CBR_EXECUTION_PATH,
        }

        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                result = session.execute(
                    text_factory(_SELECT_RULES_SQL),
                    params,
                )
                rows = result.mappings().all()
        except Exception as exc:
            raise RuleLoadError(
                "Failed to load CBR rules from database: "
                f"{type(exc).__name__}"
            ) from exc

        return normalize_rule_rows(rows)

    def load_active_rule(self, rule_id: int) -> dict[str, Any]:
        try:
            normalized_rule_id = int(rule_id)
        except (TypeError, ValueError) as exc:
            raise RuleLoadError("Rule id must be an integer") from exc
        if normalized_rule_id <= 0:
            raise RuleLoadError("Rule id must be positive")

        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(text_factory(_SET_READ_ONLY_SQL))
                result = session.execute(
                    text_factory(_SELECT_ACTIVE_RULE_BY_ID_SQL),
                    {
                        "rule_id": normalized_rule_id,
                        "status": "active",
                    },
                )
                rows = result.mappings().all()
        except Exception as exc:
            raise RuleLoadError(
                "Failed to load active rule from database: "
                f"{type(exc).__name__}"
            ) from exc

        if len(rows) != 1:
            raise RuleLoadError(
                f"Active rule id={normalized_rule_id} was not found"
            )
        return normalize_rule_rows(rows)[0]

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory

        if session_factory is None:
            if not self._database_url:
                raise RuleLoadError("CBR database URL is not configured")
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise RuleLoadError(
                    "Database support requires SQLAlchemy and a "
                    "PostgreSQL driver"
                ) from exc

            database_url = _normalize_database_url(self._database_url)
            try:
                self._engine = create_engine(
                    database_url,
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
                raise RuleLoadError(
                    "Failed to initialize CBR database connection: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory

        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise RuleLoadError(
                    "Database support requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory

        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def normalize_rule_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for row in rows:
        try:
            row_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuleLoadError(
                "Database returned a rule with an invalid id"
            ) from exc

        raw_params = row.get("params")
        params = (
            dict(raw_params)
            if isinstance(raw_params, Mapping)
            else {}
        )
        rules.append(
            {
                "id": row_id,
                "type": str(row.get("type") or ""),
                "ticker": str(row.get("ticker") or ""),
                "rule_key": str(row.get("rule_key") or "default"),
                "status": str(row.get("status") or ""),
                "priority": _int_or_none(row.get("priority")),
                "params": params,
                "tg_chat_id": row.get("tg_chat_id"),
                "account_name": row.get("account_name"),
                "condition_id": row.get("condition_id"),
                "question": row.get("question"),
                "order_qty": _float_or_none(row.get("order_qty")),
                "order_price": _float_or_none(row.get("order_price")),
            }
        )
    return rules


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
