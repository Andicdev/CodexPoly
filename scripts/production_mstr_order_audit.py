from __future__ import annotations

import json
import sys
from typing import Any

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionSettings,
)


_SCOPES = (
    "mstr-btc:2026-07-21:2026-07-27:purchase-any",
    "mstr-btc:2026-07-21:2026-07-27:purchase-over-1000",
    "mstr-btc:2026-07-21:2026-07-27:sale-any",
)


def main() -> int:
    engine: Any | None = None
    gateway: PolymarketSupervisionOrderGateway | None = None
    try:
        from sqlalchemy import create_engine, text

        hosted = HostedResolutionSettings.from_env()
        safety = LiveSafetySettings.from_env()
        engine = create_engine(
            hosted.database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            rows = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                            scope_id,
                            outcome,
                            effective_price,
                            quantity,
                            result -> 'order_ids' ->> 0 AS order_id
                        FROM resolution_execution_claims
                        WHERE scope_id = ANY(:scopes)
                          AND status = 'EXECUTED'
                        ORDER BY scope_id
                        """
                    ),
                    {"scopes": list(_SCOPES)},
                ).mappings()
            )
        if len(rows) != 3 or any(
            not str(row.get("order_id") or "").strip()
            for row in rows
        ):
            raise RuntimeError("executed_order_set_mismatch")

        gateway = PolymarketSupervisionOrderGateway(
            database_url=hosted.database_url or "",
            safety=safety,
        )
        orders: list[dict[str, object]] = []
        for row in rows:
            inspection = gateway.inspect_orders(
                account_name="abccbaq",
                order_ids=(str(row["order_id"]),),
            )
            snapshots = tuple(inspection.snapshots)
            if inspection.failed_order_ids or len(snapshots) != 1:
                raise RuntimeError("remote_order_inspection_failed")
            snapshot = snapshots[0]
            scope_id = str(row["scope_id"])
            orders.append(
                {
                    "profile": scope_id.rsplit(":", 1)[-1],
                    "outcome": str(row["outcome"]),
                    "effective_price": str(row["effective_price"]),
                    "quantity": str(row["quantity"]),
                    "state": snapshot.state.value,
                    "original_quantity": _string_or_none(
                        snapshot.original_quantity
                    ),
                    "matched_quantity": _string_or_none(
                        snapshot.matched_quantity
                    ),
                    "remaining_quantity": _string_or_none(
                        snapshot.remaining_quantity
                    ),
                }
            )
        payload = {
            "ok": True,
            "order_count": len(orders),
            "all_terminal": all(
                item["state"] in {"FILLED", "CANCELLED"}
                for item in orders
            ),
            "orders": orders,
        }
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass
        if engine is not None:
            engine.dispose()


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
