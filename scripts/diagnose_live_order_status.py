from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.secret_guard import redact_exception


_CONFIRMATION = "READ_ONLY_ORDER_INSPECTION"
_SELECT_EXECUTED_CLAIM_SQL = """
SELECT account_name, result
FROM resolution_execution_claims
WHERE scope_id = :scope_id
  AND status = 'EXECUTED'
ORDER BY id DESC
LIMIT 1
""".strip()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    if args.confirm != _CONFIRMATION:
        _print(
            {
                "ok": False,
                "error": "explicit read-only confirmation is required",
                "orders_changed": False,
            },
            stream=sys.stderr,
        )
        return 2

    runtime_environ = os.environ if environ is None else environ
    database = resolve_database_selection("primary", runtime_environ)
    if not database.url:
        _print(
            {
                "ok": False,
                "error": database.error or "database is not configured",
                "orders_changed": False,
            },
            stream=sys.stderr,
        )
        return 3

    engine = None
    gateway = None
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        engine = create_engine(
            database.url,
            pool_pre_ping=True,
            poolclass=NullPool,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            row = connection.execute(
                text(_SELECT_EXECUTED_CLAIM_SQL),
                {"scope_id": args.scope_id},
            ).mappings().one_or_none()
        if row is None:
            raise ValueError("executed claim was not found")

        result = row["result"]
        if not isinstance(result, Mapping):
            raise ValueError("executed claim result is not an object")
        order_ids = tuple(
            str(value or "").strip()
            for value in result.get("order_ids", ())
            if str(value or "").strip()
        )
        if not order_ids:
            raise ValueError("executed claim has no order IDs")

        gateway = PolymarketSupervisionOrderGateway(
            database_url=database.url,
            safety=LiveSafetySettings.from_env(runtime_environ),
        )
        inspection = gateway.inspect_orders(
            account_name=str(row["account_name"]),
            order_ids=order_ids,
        )
        _print(
            {
                "ok": not inspection.failed_order_ids,
                "mode": "read_only_order_inspection",
                "scope_id": args.scope_id,
                "orders_changed": False,
                "requested": len(inspection.requested_order_ids),
                "failed": len(inspection.failed_order_ids),
                "error": inspection.error,
                "orders": [
                    {
                        "state": snapshot.state.value,
                        "remote_status": snapshot.remote_status,
                        "side": snapshot.side.value,
                        "limit_price": str(snapshot.limit_price),
                        "original_quantity": str(
                            snapshot.original_quantity
                        ),
                        "matched_quantity": str(
                            snapshot.matched_quantity
                        ),
                        "remaining_quantity": str(
                            Decimal(snapshot.original_quantity)
                            - Decimal(snapshot.matched_quantity)
                        ),
                        "observed_at": (
                            snapshot.observed_at.isoformat()
                        ),
                    }
                    for snapshot in inspection.snapshots
                ],
            }
        )
        return 0 if not inspection.failed_order_ids else 5
    except Exception as exc:
        _print(
            {
                "ok": False,
                "mode": "read_only_order_inspection",
                "scope_id": args.scope_id,
                "error": redact_exception(exc),
                "orders_changed": False,
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        if gateway is not None:
            gateway.close()
        if engine is not None:
            engine.dispose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect remote orders referenced by one executed resolution "
            "claim without cancelling or replacing them."
        )
    )
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _print(
    payload: object,
    *,
    stream: object = sys.stdout,
) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
