from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.earnings.parsers import checked_in_shadow_rules
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.repository import SqlAlchemyEarningsStore
from cbr_trading.secret_guard import redact_exception


_EXCLUDED_TABLES_SQL = """
(
    'resolution_order_groups',
    'resolution_order_group_orders',
    'resolution_supervision_events',
    'resolution_order_observations',
    'resolution_execution_claims',
    'earnings_market_rules',
    'earnings_source_events',
    'earnings_fact_candidates'
)
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly apply the additive earnings shadow schema."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly apply migration 004 before checking it.",
    )
    parser.add_argument(
        "--seed-nvts-shadow",
        action="store_true",
        help=(
            "Insert or update only the checked-in NVTS Q2 2026 SHADOW rule. "
            "This never enables trading."
        ),
    )
    parser.add_argument(
        "--seed-checked-in-shadow",
        action="store_true",
        help=(
            "Insert or update every checked-in SHADOW earnings rule. "
            "This never enables trading."
        ),
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

    store = SqlAlchemyEarningsStore(database_url=database.url)
    try:
        before = _snapshot(database.url)
        if args.apply:
            store.migrate()
        after_migration = _snapshot(database.url)
        if after_migration["schema_exists"]:
            store.ensure_ready()
        seeded_rule_id = None
        seeded_rule_ids: dict[str, int] = {}
        rules_to_seed = (
            checked_in_shadow_rules()
            if args.seed_checked_in_shadow
            else (
                (nvts_q2_2026_shadow_rule(),)
                if args.seed_nvts_shadow
                else ()
            )
        )
        if rules_to_seed:
            if not after_migration["schema_exists"]:
                raise RuntimeError(
                    "Earnings schema must exist before seeding"
                )
            for rule in rules_to_seed:
                seeded_rule_ids[rule.rule_key] = (
                    store.save_shadow_rule(rule)
                )
            seeded_rule_id = seeded_rule_ids.get(
                nvts_q2_2026_shadow_rule().rule_key
            )
        after = _snapshot(database.url)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "applied": bool(args.apply),
                    "seeded_nvts_shadow": bool(
                        args.seed_nvts_shadow
                    ),
                    "seeded_checked_in_shadow": bool(
                        args.seed_checked_in_shadow
                    ),
                    "error": redact_exception(
                        RuntimeError(
                            "Earnings schema operation failed: "
                            f"{type(exc).__name__}"
                        )
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 5
    finally:
        store.close()

    legacy_unchanged = (
        before["legacy_tables"] == after["legacy_tables"]
        and before["legacy_columns"] == after["legacy_columns"]
    )
    no_runtime_rows = (
        after["source_event_rows"] == 0
        and after["fact_candidate_rows"] == 0
    )
    payload = {
        "ok": (
            bool(after["schema_exists"])
            and legacy_unchanged
            and no_runtime_rows
        ),
        "target": database.target,
        "applied": bool(args.apply),
        "seeded_nvts_shadow": bool(args.seed_nvts_shadow),
        "seeded_checked_in_shadow": bool(
            args.seed_checked_in_shadow
        ),
        "seeded_rule_id": seeded_rule_id,
        "seeded_rule_ids": seeded_rule_ids,
        "legacy_unchanged": legacy_unchanged,
        "no_runtime_rows": no_runtime_rows,
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
            "Earnings schema management requires SQLAlchemy"
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
            existing = {
                str(row["table_name"])
                for row in connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = current_schema()
                          AND table_name IN (
                              'earnings_market_rules',
                              'earnings_source_events',
                              'earnings_fact_candidates'
                          )
                        """
                    )
                ).mappings()
            }
            schema_exists = existing == {
                "earnings_market_rules",
                "earnings_source_events",
                "earnings_fact_candidates",
            }
            market_rule_rows = _count_rows(
                connection,
                text,
                "earnings_market_rules",
                exists="earnings_market_rules" in existing,
            )
            source_event_rows = _count_rows(
                connection,
                text,
                "earnings_source_events",
                exists="earnings_source_events" in existing,
            )
            fact_candidate_rows = _count_rows(
                connection,
                text,
                "earnings_fact_candidates",
                exists="earnings_fact_candidates" in existing,
            )
    finally:
        engine.dispose()
    return {
        "legacy_tables": legacy_tables,
        "legacy_columns": legacy_columns,
        "schema_exists": schema_exists,
        "market_rule_rows": market_rule_rows,
        "source_event_rows": source_event_rows,
        "fact_candidate_rows": fact_candidate_rows,
    }


def _count_rows(
    connection: Any,
    text_factory: Any,
    table_name: str,
    *,
    exists: bool,
) -> int | None:
    if not exists:
        return None
    allowed = {
        "earnings_market_rules",
        "earnings_source_events",
        "earnings_fact_candidates",
    }
    if table_name not in allowed:
        raise ValueError("unsupported earnings table")
    return int(
        connection.execute(
            text_factory(f"SELECT count(*) FROM {table_name}")
        ).scalar_one()
    )


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
