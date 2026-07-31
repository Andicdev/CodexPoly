from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Sequence

from neg_risk_trading.domain import (
    NegRiskContractError,
    RouteDirection,
)
from neg_risk_trading.polymarket import (
    DEFAULT_FED_SEPTEMBER_SLUG,
    PolymarketPublicClient,
    PublicApiError,
)
from neg_risk_trading.scanner import evaluate_snapshot


def _quantities(value: str) -> tuple[Decimal, ...]:
    try:
        quantities = tuple(
            Decimal(part.strip())
            for part in value.split(",")
            if part.strip()
        )
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(
            "quantities must be comma-separated decimals"
        ) from exc
    if not quantities or any(item <= 0 for item in quantities):
        raise argparse.ArgumentTypeError(
            "quantities must be positive"
        )
    return quantities


def _directions(value: str) -> tuple[RouteDirection, ...]:
    aliases = {
        "buy": RouteDirection.MAKER_BUY,
        "maker-buy": RouteDirection.MAKER_BUY,
        "maker_buy": RouteDirection.MAKER_BUY,
        "sell": RouteDirection.MAKER_SELL,
        "maker-sell": RouteDirection.MAKER_SELL,
        "maker_sell": RouteDirection.MAKER_SELL,
    }
    try:
        directions = tuple(
            aliases[part.strip().lower()]
            for part in value.split(",")
            if part.strip()
        )
    except KeyError as exc:
        raise argparse.ArgumentTypeError(
            "directions must contain maker-buy and/or maker-sell"
        ) from exc
    if not directions or len(directions) != len(set(directions)):
        raise argparse.ArgumentTypeError(
            "directions must be unique"
        )
    return directions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only strict neg-risk basket opportunity scanner."
        )
    )
    parser.add_argument(
        "--event",
        default=DEFAULT_FED_SEPTEMBER_SLUG,
        help="Polymarket event slug or /event/<slug> URL.",
    )
    parser.add_argument(
        "--quantities",
        type=_quantities,
        default=_quantities("20,50,100,200,500"),
        help="Comma-separated basket quantities.",
    )
    parser.add_argument(
        "--directions",
        type=_directions,
        default=_directions("maker-buy,maker-sell"),
        help="Comma-separated maker-buy and/or maker-sell routes.",
    )
    parser.add_argument(
        "--maximum-books-duration-ms",
        type=int,
        default=2_000,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot = PolymarketPublicClient().fetch_snapshot(
            args.event
        )
        payload = evaluate_snapshot(
            snapshot,
            quantities=args.quantities,
            route_directions=args.directions,
            maximum_books_duration_ms=(
                args.maximum_books_duration_ms
            ),
        )
    except PublicApiError as exc:
        payload = {
            "mode": "READ_ONLY_SHADOW",
            "ok": False,
            "reason_code": exc.reason_code,
        }
        print(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
        return 2
    except NegRiskContractError as exc:
        payload = {
            "mode": "READ_ONLY_SHADOW",
            "ok": False,
            "reason_code": str(exc),
        }
        print(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
        return 2

    payload["ok"] = True
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
