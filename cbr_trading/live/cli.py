from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.live.account_repository import (
    SqlAlchemyTradingAccountRepository,
    TradingAccountLoadError,
)
from cbr_trading.live.executor import (
    LiveOrderError,
    LiveOrderExecutor,
)
from cbr_trading.live.market import (
    MarketPreflightError,
    PolymarketMarketGateway,
)
from cbr_trading.live.runner_executor import WarmLiveOrderExecutor
from cbr_trading.live.safety import (
    LiveSafetySettings,
    build_live_order_plan,
)
from cbr_trading.rule_repository import (
    RuleLoadError,
    SqlAlchemyRuleRepository,
)
from cbr_trading.trading_rules import resolve_order_price


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)

    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        _print_json(
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

    if args.runner_preflight:
        return _run_runner_preflight(
            database_url=database.url,
            database_target=database.target,
        )
    if not args.action:
        _print_json(
            {
                "ok": False,
                "error": (
                    "--action YES|NO is required unless "
                    "--runner-preflight is used"
                ),
            },
            stream=sys.stderr,
        )
        return 2

    rule_repository = SqlAlchemyRuleRepository(
        database_url=database.url
    )
    account_repository = SqlAlchemyTradingAccountRepository(
        database_url=database.url
    )
    try:
        rules = rule_repository.load_active_cbr_rules()
        rule = _select_rule(rules, rule_id=args.rule_id)
        action = args.action.upper()
        quantity = _required_decimal(
            rule.get("order_qty"),
            name="order_qty",
        )
        limit_price = _required_decimal(
            resolve_order_price(rule, action),
            name=f"{action} order price",
        )
        account = account_repository.load_active(
            str(rule.get("account_name") or "")
        )
        snapshot = PolymarketMarketGateway().load_snapshot(
            condition_id=str(rule.get("condition_id") or ""),
            outcome=action,
        )
        safety = LiveSafetySettings.from_env()
        plan = build_live_order_plan(
            account=account,
            rule_id=rule.get("id"),
            rule_key=str(rule.get("rule_key") or ""),
            quantity=quantity,
            limit_price=limit_price,
            snapshot=snapshot,
            settings=safety,
        )
    except (
        RuleLoadError,
        TradingAccountLoadError,
        MarketPreflightError,
        ValueError,
    ) as exc:
        _print_json(
            {"ok": False, "error": str(exc)},
            stream=sys.stderr,
        )
        return 3
    finally:
        rule_repository.close()
        account_repository.close()

    _print_json(
        _preview_payload(
            plan=plan,
            mode="apply" if args.apply else "preview",
            database_target=database.target,
            live_enabled=safety.trading_enabled,
            master_key_present=bool(safety.accounts_master_key),
        )
    )

    if args.auth_check:
        try:
            checked = LiveOrderExecutor().check_authenticated(
                plan=plan,
                account=account,
                settings=safety,
            )
        except LiveOrderError as exc:
            _print_json(
                {"ok": False, "error": str(exc)},
                stream=sys.stderr,
            )
            return 5
        _print_json(
            {
                "ok": True,
                "mode": "authenticated_preflight",
                "order_submitted": False,
                "wallet_type": checked.wallet_type,
                "collateral_balance": str(
                    checked.collateral_balance
                ),
                "current_best_ask": _decimal_or_none(
                    checked.current_best_ask
                ),
            }
        )
        return 0

    if not args.apply:
        return 0
    if not args.confirm_live_order:
        _print_json(
            {
                "ok": False,
                "error": (
                    "--confirm-live-order is required with --apply"
                ),
            },
            stream=sys.stderr,
        )
        return 4
    if not plan.ready_to_apply:
        _print_json(
            {
                "ok": False,
                "error": "Live order is blocked by safety checks",
                "blockers": list(plan.blockers),
            },
            stream=sys.stderr,
        )
        return 4

    try:
        result = LiveOrderExecutor().place(
            plan=plan,
            account=account,
            settings=safety,
        )
    except LiveOrderError as exc:
        _print_json(
            {"ok": False, "error": str(exc)},
            stream=sys.stderr,
        )
        return 5

    _print_json(
        {
            "ok": result.accepted,
            "mode": "live_result",
            "attempted": result.attempted,
            "accepted": result.accepted,
            "order_id": result.order_id,
            "status": result.status,
            "error_code": result.error_code,
            "message": result.message,
            "wallet_type": result.wallet_type,
            "collateral_balance": str(
                result.collateral_balance
            ),
        }
    )
    return 0 if result.accepted else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview one active CBR rule against the current Polymarket "
            "book. Order submission requires three opt-ins: "
            "CBR_LIVE_TRADING_ENABLED=1, --apply, and "
            "--confirm-live-order."
        )
    )
    parser.add_argument(
        "--action",
        choices=("YES", "NO", "yes", "no"),
        help="Outcome token to BUY for this isolated live check.",
    )
    parser.add_argument(
        "--rule-id",
        type=int,
        default=None,
        help=(
            "Active monitored_news id. When omitted, exactly one "
            "active CBR fast-path rule must exist."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--auth-check",
        action="store_true",
        help=(
            "Decrypt and authenticate the account, verify wallet type, "
            "balance, and the latest book, but never submit an order. "
            "This may derive or create CLOB API credentials."
        ),
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Enable the order-submission branch.",
    )
    mode_group.add_argument(
        "--runner-preflight",
        action="store_true",
        help=(
            "Warm every active CBR rule exactly as the continuous live "
            "runner will, including the account, balance, both outcome "
            "books, and idempotency table. Never submits an order."
        ),
    )
    parser.add_argument(
        "--confirm-live-order",
        action="store_true",
        help=(
            "Acknowledge that the real post-only GTC order can fill "
            "later while it remains on the book."
        ),
    )
    return parser


def _run_runner_preflight(
    *,
    database_url: str,
    database_target: str,
) -> int:
    rule_repository = SqlAlchemyRuleRepository(
        database_url=database_url
    )
    try:
        rules = rule_repository.load_active_cbr_rules()
    except RuleLoadError as exc:
        _print_json(
            {"ok": False, "error": str(exc)},
            stream=sys.stderr,
        )
        return 3
    finally:
        rule_repository.close()

    safety = LiveSafetySettings.from_env()
    validation_safety = replace(safety, trading_enabled=True)
    executor = WarmLiveOrderExecutor(
        subscriptions=rules,
        database_url=database_url,
        safety=validation_safety,
    )
    try:
        summary = executor.prepare()
    except Exception as exc:
        _print_json(
            {
                "ok": False,
                "mode": "runner_preflight",
                "order_submitted": False,
                "error": _safe_exception(exc),
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        executor.close()

    _print_json(
        {
            "ok": True,
            "mode": "runner_preflight",
            "order_submitted": False,
            "database_target": database_target,
            "rules": summary.rule_count,
            "accounts": summary.account_count,
            "prepared_outcomes": summary.outcome_count,
            "maximum_notional": str(summary.maximum_notional),
            "safety": {
                "live_trading_enabled": safety.trading_enabled,
                "post_only": safety.post_only,
                "allowed_account": safety.allowed_account,
                "max_order_quantity": _decimal_or_none(
                    safety.max_order_quantity
                ),
                "max_notional": _decimal_or_none(
                    safety.max_notional
                ),
                "max_total_notional": _decimal_or_none(
                    safety.max_total_notional
                ),
                "master_key_present": bool(
                    safety.accounts_master_key
                ),
            },
        }
    )
    return 0


def _select_rule(
    rules: Sequence[Mapping[str, Any]],
    *,
    rule_id: int | None,
) -> Mapping[str, Any]:
    if rule_id is not None:
        matches = [
            rule
            for rule in rules
            if rule.get("id") == rule_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Active CBR rule id={rule_id} was not found"
            )
        return matches[0]

    if len(rules) != 1:
        raise ValueError(
            "Expected exactly one active CBR rule when --rule-id is "
            f"omitted; found {len(rules)}"
        )
    return rules[0]


def _required_decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Rule has invalid {name}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Rule has invalid {name}")
    return parsed


def _preview_payload(
    *,
    plan: Any,
    mode: str,
    database_target: str,
    live_enabled: bool,
    master_key_present: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": mode,
        "database_target": database_target,
        "rule": {
            "id": plan.rule_id,
            "rule_key": plan.rule_key,
            "condition_id": plan.condition_id,
            "question": plan.question,
        },
        "account": {
            "name": plan.account_name,
            "wallet": plan.wallet_masked,
            "signature_type": plan.signature_type,
            "master_key_present": master_key_present,
        },
        "order": {
            "side": plan.side,
            "outcome": plan.outcome,
            "token_id": plan.token_id,
            "quantity": str(plan.quantity),
            "limit_price": str(plan.limit_price),
            "max_notional": str(plan.notional),
            "post_only": plan.post_only,
            "time_in_force": plan.time_in_force,
        },
        "market": {
            "best_bid": _decimal_or_none(plan.best_bid),
            "best_ask": _decimal_or_none(plan.best_ask),
            "last_trade_price": _decimal_or_none(
                plan.last_trade_price
            ),
            "tick_size": str(plan.tick_size),
            "minimum_order_size": str(
                plan.minimum_order_size
            ),
        },
        "safety": {
            "live_trading_enabled": live_enabled,
            "ready_to_apply": plan.ready_to_apply,
            "blockers": list(plan.blockers),
        },
    }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _safe_exception(exc: Exception) -> str:
    detail = " ".join(str(exc).split())[:240]
    return (
        f"{type(exc).__name__}: {detail}"
        if detail
        else type(exc).__name__
    )


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
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=stream if stream is not None else sys.stdout,
    )
