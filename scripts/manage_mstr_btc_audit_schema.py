from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.mstr_btc import SqlAlchemyMstrBtcAuditStore
from cbr_trading.secret_guard import redact_exception


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly apply the additive append-only "
            "MSTR BTC source audit schema."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicitly apply migration 009. Production should use the "
            "stdin-only migration runner instead."
        ),
    )
    args = parser.parse_args(argv)

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

    store = SqlAlchemyMstrBtcAuditStore(database_url=database.url)
    try:
        if args.apply:
            store.migrate()
        store.ensure_ready()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "applied": bool(args.apply),
                    "error": redact_exception(
                        RuntimeError(
                            "MSTR source audit schema operation failed: "
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

    print(
        json.dumps(
            {
                "ok": True,
                "target": database.target,
                "applied": bool(args.apply),
                "schema_ready": True,
            },
            indent=2,
        )
    )
    return 0


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
