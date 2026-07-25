from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.domain import KeepOpenPolicy, RepriceOnTickChange
from cbr_trading.earnings import (
    EarningsMarketRule,
    SqlAlchemyEarningsStore,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources.earnings import EARNINGS_SOURCE_NAME


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)
    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        _print(
            {
                "ok": False,
                "error": (
                    database.error
                    or "Primary database URL is not configured"
                ),
            },
            stream=sys.stderr,
        )
        return 3

    profile_store = SqlAlchemyResolutionProfileStore(
        database_url=database.url
    )
    earnings_store: SqlAlchemyEarningsStore | None = None
    try:
        if args.apply:
            profile_store.migrate()
        profile_store.ensure_ready()
        payload: dict[str, object] = {
            "ok": True,
            "database_target": database.target,
            "schema_ready": True,
            "migration_applied": bool(args.apply),
        }
        if args.configure_earnings:
            earnings_store = SqlAlchemyEarningsStore(
                database_url=database.url
            )
            earnings_store.ensure_ready()
            rule = _select_rule(
                earnings_store.load_active_rules(),
                ticker=args.configure_earnings,
            )
            profile = _profile_from_args(rule, args=args)
            stored = profile_store.save(profile)
            payload["configured"] = {
                "profile_key": profile.profile_key,
                "scope_id": profile.scope_id,
                "ticker": rule.ticker,
                "row_id": stored.row_id,
                "status": "DISABLED",
            }
        if args.enable_profile or args.disable_profile:
            profile_key = (
                args.enable_profile or args.disable_profile
            )
            enabled = bool(args.enable_profile)
            stored = profile_store.set_enabled(
                profile_key,
                enabled=enabled,
            )
            payload["status_updated"] = {
                "profile_key": profile_key,
                "row_id": stored.row_id,
                "status": (
                    "ENABLED" if enabled else "DISABLED"
                ),
            }
        _print(payload)
        return 0
    except Exception as exc:
        _print(
            {
                "ok": False,
                "error": redact_exception(exc),
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        if earnings_store is not None:
            earnings_store.close()
        profile_store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly manage additive source-neutral "
            "resolution execution profiles."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly apply additive migration 005.",
    )
    parser.add_argument(
        "--configure-earnings",
        metavar="TICKER",
        help=(
            "Create or update one disabled profile from an active "
            "earnings source rule."
        ),
    )
    parser.add_argument("--account-name")
    parser.add_argument("--yes-price", type=Decimal)
    parser.add_argument("--no-price", type=Decimal)
    parser.add_argument("--quantity", type=Decimal)
    parser.add_argument(
        "--prepare-from",
        type=_utc_datetime,
        help="UTC ISO-8601 beginning of the preparation window.",
    )
    parser.add_argument(
        "--expires-at",
        type=_utc_datetime,
        help="UTC ISO-8601 hard expiry for this execution profile.",
    )
    parser.add_argument(
        "--lifecycle",
        choices=("reprice_on_tick_change", "keep_open"),
        default="reprice_on_tick_change",
    )
    parser.add_argument(
        "--old-tick",
        type=Decimal,
        default=Decimal("0.01"),
    )
    parser.add_argument(
        "--new-tick",
        type=Decimal,
        default=Decimal("0.001"),
    )
    parser.add_argument(
        "--max-reprices",
        type=int,
        default=1,
    )
    status = parser.add_mutually_exclusive_group()
    status.add_argument("--enable-profile", metavar="PROFILE_KEY")
    status.add_argument("--disable-profile", metavar="PROFILE_KEY")
    return parser


def _profile_from_args(
    rule: EarningsMarketRule,
    *,
    args: argparse.Namespace,
) -> ResolutionExecutionProfile:
    required = {
        "--account-name": args.account_name,
        "--yes-price": args.yes_price,
        "--no-price": args.no_price,
        "--quantity": args.quantity,
        "--prepare-from": args.prepare_from,
        "--expires-at": args.expires_at,
    }
    missing = [
        option
        for option, value in required.items()
        if value is None or str(value).strip() == ""
    ]
    if missing:
        raise ValueError(
            "--configure-earnings requires "
            + ", ".join(missing)
        )
    if not rule.condition_id or not rule.market_slug:
        raise ValueError(
            "earnings source rule has no Polymarket identity"
        )
    if args.lifecycle == "keep_open":
        policy = KeepOpenPolicy()
    else:
        policy = RepriceOnTickChange(
            old_tick=args.old_tick,
            new_tick=args.new_tick,
            max_reprices=args.max_reprices,
        )
    return ResolutionExecutionProfile(
        profile_key=(
            f"earnings-{rule.ticker.lower()}-"
            f"{rule.fiscal_year}q{rule.fiscal_quarter}"
        ),
        scope_id=rule.scope_id,
        source_name=EARNINGS_SOURCE_NAME,
        source_reference=(
            f"https://polymarket.com/event/{rule.market_slug}"
        ),
        account_name=args.account_name,
        condition_id=rule.condition_id,
        yes_desired_price=args.yes_price,
        no_desired_price=args.no_price,
        quantity=args.quantity,
        prepare_from=args.prepare_from,
        expires_at=args.expires_at,
        lifecycle_policy=policy,
        metadata={
            "rule_key": rule.rule_key,
            "ticker": rule.ticker,
        },
    )


def _select_rule(
    rules: Sequence[EarningsMarketRule],
    *,
    ticker: str,
) -> EarningsMarketRule:
    normalized = str(ticker or "").strip().upper()
    matches = tuple(
        rule for rule in rules if rule.ticker == normalized
    )
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one active earnings rule for ticker"
        )
    return matches[0]


def _utc_datetime(value: str) -> datetime:
    normalized = str(value or "").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "expected an ISO-8601 datetime"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "datetime must include a UTC offset"
        )
    return parsed.astimezone(timezone.utc)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _print(
    payload: object,
    *,
    stream: object = sys.stdout,
) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
