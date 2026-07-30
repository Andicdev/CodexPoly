from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Sequence

from neg_risk_trading.domain import NegRiskContractError
from neg_risk_trading.market_stream import (
    MarketStreamTransportError,
    PolymarketMarketStream,
)
from neg_risk_trading.polymarket import (
    DEFAULT_FED_SEPTEMBER_SLUG,
    PolymarketPublicClient,
    PublicApiError,
)
from neg_risk_trading.stream import (
    LocalBookRegistry,
    asset_configs_from_books,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only neg-risk market WebSocket bootstrap probe."
        )
    )
    parser.add_argument(
        "--event",
        default=DEFAULT_FED_SEPTEMBER_SLUG,
    )
    parser.add_argument(
        "--bootstrap-timeout-seconds",
        type=float,
        default=15.0,
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    bootstrap_started = time.perf_counter_ns()
    bootstrap = PolymarketPublicClient().fetch_stream_bootstrap(
        args.event
    )
    bootstrap_elapsed_ms = (
        time.perf_counter_ns() - bootstrap_started
    ) // 1_000_000
    registry = LocalBookRegistry(
        event=bootstrap.event,
        assets=asset_configs_from_books(
            event=bootstrap.event,
            books=bootstrap.books,
        ),
        clock_ms=lambda: time.time_ns() // 1_000_000,
    )
    stream_started = time.perf_counter_ns()
    result = await PolymarketMarketStream(
        bootstrap_timeout_seconds=(
            args.bootstrap_timeout_seconds
        )
    ).run_once(
        registry,
        stop_when_ready=True,
    )
    stream_elapsed_ms = (
        time.perf_counter_ns() - stream_started
    ) // 1_000_000
    return {
        "mode": "READ_ONLY_SHADOW",
        "ok": True,
        "event_slug": bootstrap.event.slug,
        "market_count": len(bootstrap.event.markets),
        "asset_count": len(bootstrap.event.asset_ids),
        "rest_bootstrap_ms": int(bootstrap_elapsed_ms),
        "gamma_duration_ms": bootstrap.gamma_duration_ms,
        "books_duration_ms": bootstrap.books_duration_ms,
        "websocket_initial_dump_ms": int(stream_elapsed_ms),
        "websocket_message_count": result.message_count,
        "websocket_update_count": result.update_count,
        "websocket_reached_ready": result.reached_ready,
        "websocket_status_at_exit": (
            result.status_at_exit.value
        ),
        "live_orders_enabled": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
    except (
        PublicApiError,
        MarketStreamTransportError,
    ) as exc:
        payload = {
            "mode": "READ_ONLY_SHADOW",
            "ok": False,
            "reason_code": exc.reason_code,
        }
        print(json.dumps(payload, indent=2))
        return 2
    except NegRiskContractError as exc:
        payload = {
            "mode": "READ_ONLY_SHADOW",
            "ok": False,
            "reason_code": str(exc),
        }
        print(json.dumps(payload, indent=2))
        return 2
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
