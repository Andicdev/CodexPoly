from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from cbr_trading.admin.templates import RuleDraft


_LOCK_SQL = """
SELECT pg_advisory_xact_lock(
    hashtext('cbr_trading:monitored_news_admin')
)
""".strip()

_FIND_SQL = """
SELECT id
FROM monitored_news
WHERE type = :type
  AND ticker = :ticker
  AND rule_key = :rule_key
ORDER BY id
FOR UPDATE
""".strip()

_INSERT_SQL = """
INSERT INTO monitored_news (
    type,
    ticker,
    rule_key,
    status,
    priority,
    tg_chat_id,
    account_name,
    condition_id,
    question,
    order_qty,
    order_price,
    params,
    created_at,
    updated_at
) VALUES (
    :type,
    :ticker,
    :rule_key,
    :status,
    :priority,
    :tg_chat_id,
    :account_name,
    :condition_id,
    :question,
    :order_qty,
    :order_price,
    CAST(:params_json AS jsonb),
    NOW(),
    NOW()
)
RETURNING id
""".strip()

_UPDATE_SQL = """
UPDATE monitored_news
SET
    status = :status,
    priority = :priority,
    tg_chat_id = :tg_chat_id,
    account_name = :account_name,
    condition_id = :condition_id,
    question = :question,
    order_qty = :order_qty,
    order_price = :order_price,
    params = CAST(:params_json AS jsonb),
    updated_at = NOW()
WHERE id = :id
RETURNING id
""".strip()


class RuleWriteError(RuntimeError):
    """Safe failure raised by the explicit administrative write path."""


@dataclass(frozen=True)
class RuleWriteResult:
    rule_id: int
    rule_key: str
    action: str
    condition_id: str


class SqlAlchemyRuleWriter:
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
            "<SqlAlchemyRuleWriter "
            f"configured={bool(self._database_url)!r}>"
        )

    def apply_rules(
        self,
        drafts: Sequence[RuleDraft],
    ) -> list[RuleWriteResult]:
        if not drafts:
            raise RuleWriteError("No CBR rule drafts were supplied")
        session_factory, text_factory = self._resolve_dependencies()

        try:
            with session_factory() as session:
                with session.begin():
                    session.execute(text_factory(_LOCK_SQL))
                    results = [
                        self._upsert_one(
                            session=session,
                            text_factory=text_factory,
                            draft=draft,
                        )
                        for draft in drafts
                    ]
        except RuleWriteError:
            raise
        except Exception as exc:
            raise RuleWriteError(
                "Failed to write CBR rules: "
                f"{type(exc).__name__}"
            ) from exc

        return results

    def _upsert_one(
        self,
        *,
        session: Any,
        text_factory: Callable[[str], Any],
        draft: RuleDraft,
    ) -> RuleWriteResult:
        record = draft.as_record()
        identity = {
            "type": record["type"],
            "ticker": record["ticker"],
            "rule_key": record["rule_key"],
        }
        existing_ids = (
            session.execute(
                text_factory(_FIND_SQL),
                identity,
            )
            .scalars()
            .all()
        )
        if len(existing_ids) > 1:
            raise RuleWriteError(
                "Multiple monitored_news rows exist for "
                f"rule_key={draft.rule_key!r}"
            )

        values = {
            **identity,
            "status": record["status"],
            "priority": int(record["priority"]),
            "tg_chat_id": record["tg_chat_id"],
            "account_name": record["account_name"],
            "condition_id": record["condition_id"],
            "question": record["question"],
            "order_qty": float(record["order_qty"]),
            "order_price": float(record["order_price"]),
            "params_json": json.dumps(
                record["params"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }

        if existing_ids:
            values["id"] = int(existing_ids[0])
            rule_id = session.execute(
                text_factory(_UPDATE_SQL),
                values,
            ).scalar_one()
            action = "updated"
        else:
            rule_id = session.execute(
                text_factory(_INSERT_SQL),
                values,
            ).scalar_one()
            action = "created"

        return RuleWriteResult(
            rule_id=int(rule_id),
            rule_key=draft.rule_key,
            action=action,
            condition_id=draft.condition_id,
        )

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise RuleWriteError(
                    "CBR_ADMIN_DATABASE_URL is required with --apply"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError as exc:
                raise RuleWriteError(
                    "Admin database support requires SQLAlchemy and "
                    "a PostgreSQL driver"
                ) from exc

            database_url = _normalize_database_url(self._database_url)
            try:
                self._engine = create_engine(
                    database_url,
                    pool_pre_ping=True,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise RuleWriteError(
                    "Failed to initialize admin database connection: "
                    f"{type(exc).__name__}"
                ) from exc
            self._session_factory = session_factory

        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError as exc:
                raise RuleWriteError(
                    "Admin database support requires SQLAlchemy"
                ) from exc
            text_factory = text
            self._text_factory = text_factory

        return session_factory, text_factory

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url
