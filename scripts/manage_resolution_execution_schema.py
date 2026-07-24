from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.live.resolution_idempotency import (
    SqlAlchemyResolutionExecutionLedger,
)
from cbr_trading.secret_guard import redact_exception


_EXCLUDED_TABLES_SQL = """
(
    'resolution_order_groups',
    'resolution_order_group_orders',
    'resolution_supervision_events',
    'resolution_order_observations',
    'resolution_execution_claims'
)
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly apply the additive source-neutral "
            "execution ledger migration."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly apply migration 003 before checking it.",
    )
    args = parser.parse_args()
    _load_dotenv_if_available()
    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "error": (
                        database.error
                        or "Primary database URL is not configured"
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 3

    ledger = SqlAlchemyResolutionExecutionLedger(
        database_url=database.url
    )
    try:
        before = _snapshot(database.url)
        if args.apply:
            ledger.migrate()
        after = _snapshot(database.url)
        if after["claims_exists"]:
            ledger.ensure_ready()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "applied": bool(args.apply),
                    "error": redact_exception(exc),
                }
            ),
            file=sys.stderr,
        )
        return 5
    finally:
        ledger.close()

    ready = bool(after["claims_exists"])
    newly_created_empty = (
        not args.apply
        or before["claims_exists"]
        or after["claims_rows"] == 0
    )
    unchanged = (
        before["legacy_tables"] == after["legacy_tables"]
        and before["legacy_columns"] == after["legacy_columns"]
    )
    payload = {
        "ok": ready and unchanged and newly_created_empty,
        "target": database.target,
        "applied": bool(args.apply),
        "legacy_unchanged": unchanged,
        "newly_created_empty": newly_created_empty,
        "before": before,
        "after": after,
    }
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _snapshot(database_url: str) -> dict[str, Any]:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError(
            "Schema management requires SQLAlchemy"
        ) from exc

    engine = create_engine(
        _normalize_database_url(database_url),
        pool_pre_ping=True,
        pool_recycle=300,
        pool_reset_on_return="rollback",
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            legacy_tables = int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_type = 'BASE TABLE'
                          AND table_name NOT IN
                        """
                        + _EXCLUDED_TABLES_SQL
                    )
                ).scalar_one()
            )
            legacy_columns = int(
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name NOT IN
                        """
                        + _EXCLUDED_TABLES_SQL
                    )
                ).scalar_one()
            )
            claims_exists = bool(
                connection.execute(
                    text(
                        """
                        SELECT to_regclass(
                            'resolution_execution_claims'
                        ) IS NOT NULL
                        """
                    )
                ).scalar_one()
            )
            claims_rows = (
                int(
                    connection.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM resolution_execution_claims
                            """
                        )
                    ).scalar_one()
                )
                if claims_exists
                else None
            )
    finally:
        engine.dispose()
    return {
        "legacy_tables": legacy_tables,
        "legacy_columns": legacy_columns,
        "claims_exists": claims_exists,
        "claims_rows": claims_rows,
    }


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
