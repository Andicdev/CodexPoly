from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from cbr_trading.admin.market_resolver import (
    GammaClient,
    MarketResolverError,
    extract_event_slug,
    resolve_three_way_markets,
)
from cbr_trading.admin.rule_writer import (
    RuleWriteError,
    SqlAlchemyRuleWriter,
)
from cbr_trading.admin.templates import (
    RuleTemplateConfig,
    build_three_way_rule_drafts,
)


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        slug = extract_event_slug(args.event_url)
        gamma = GammaClient(timeout=args.gamma_timeout)
        event = gamma.get_event_by_slug(slug)
        markets = resolve_three_way_markets(
            event,
            event_url=args.event_url,
        )
        config = RuleTemplateConfig(
            account_name=args.account_name,
            order_qty=args.order_qty,
            order_price_yes=args.yes_price,
            order_price_no=args.no_price,
            increase_price_yes=args.increase_yes_price,
            increase_price_no=args.increase_no_price,
            telegram_chat_id=args.telegram_chat_id,
            status=args.status,
        )
        drafts = build_three_way_rule_drafts(markets, config)
    except (MarketResolverError, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 2

    preview = {
        "ok": True,
        "mode": "apply" if args.apply else "preview",
        "template": args.template,
        "event": {
            "id": markets.event_id,
            "slug": markets.event_slug,
            "title": markets.event_title,
            "url": markets.event_url,
        },
        "rules": [draft.as_record() for draft in drafts],
    }
    _print_json(preview)

    if not args.apply:
        return 0

    writer = SqlAlchemyRuleWriter(
        database_url=os.getenv("CBR_ADMIN_DATABASE_URL"),
    )
    try:
        results = writer.apply_rules(drafts)
    except RuleWriteError as exc:
        _print_json({"ok": False, "error": str(exc)}, stream=sys.stderr)
        return 3
    finally:
        writer.close()

    _print_json(
        {
            "ok": True,
            "mode": "applied",
            "results": [
                {
                    "id": result.rule_id,
                    "rule_key": result.rule_key,
                    "action": result.action,
                    "condition_id": result.condition_id,
                }
                for result in results
            ],
        }
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a Polymarket CBR event and preview or apply the "
            "three-way key-rate trading rules."
        )
    )
    parser.add_argument("--event-url", required=True)
    parser.add_argument(
        "--template",
        choices=("cbr_three_way_key_rate",),
        default="cbr_three_way_key_rate",
    )
    parser.add_argument(
        "--account-name",
        default=os.getenv("CBR_ACCOUNT_NAME_FAST", ""),
    )
    parser.add_argument(
        "--order-qty",
        type=float,
        default=_env_float("CBR_ORDER_QTY", 10.0),
    )
    parser.add_argument(
        "--yes-price",
        type=float,
        default=_env_float("CBR_ORDER_PRICE_YES", 0.99),
    )
    parser.add_argument(
        "--no-price",
        type=float,
        default=_env_float("CBR_ORDER_PRICE_NO", 0.99),
    )
    parser.add_argument(
        "--increase-yes-price",
        type=float,
        default=_env_optional_float(
            "CBR_ORDER_PRICE_YES_INCREASE"
        ),
    )
    parser.add_argument(
        "--increase-no-price",
        type=float,
        default=_env_optional_float(
            "CBR_ORDER_PRICE_NO_INCREASE"
        ),
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("CBR_TG_CHAT_ID") or None,
    )
    parser.add_argument(
        "--status",
        choices=("active", "inactive"),
        default="active",
    )
    parser.add_argument(
        "--gamma-timeout",
        type=float,
        default=_env_float("CBR_GAMMA_TIMEOUT_SEC", 10.0),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write rules using CBR_ADMIN_DATABASE_URL. "
            "Without this flag the command only prints a preview."
        ),
    )
    return parser


def _env_float(name: str, default: float) -> float:
    value = str(os.getenv(name) or "").strip()
    return float(value) if value else default


def _env_optional_float(name: str) -> float | None:
    value = str(os.getenv(name) or "").strip()
    return float(value) if value else None


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _print_json(
    payload: object,
    *,
    stream: object | None = None,
) -> None:
    target = stream if stream is not None else sys.stdout
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=target,
    )
