from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from cbr_trading.client import DiscoveryResult
from cbr_trading.db_config import resolve_database_selection
from cbr_trading.execution import RemoteOrderState
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
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.pipeline import OrderIntent
from cbr_trading.release import build_predicted_release_url
from cbr_trading.rule_repository import (
    RuleLoadError,
    SqlAlchemyRuleRepository,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.trading_rules import resolve_order_price


_LIVE_TEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


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
    if args.full_path_live_test:
        return _run_full_path_live_test(
            args=args,
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
            (
                args.quantity
                if args.quantity is not None
                else rule.get("order_qty")
            ),
            name="order_qty",
        )
        limit_price = _required_decimal(
            (
                args.limit_price
                if args.limit_price is not None
                else resolve_order_price(rule, action)
            ),
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
            {"ok": False, "error": redact_sensitive_text(exc)},
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
                {"ok": False, "error": redact_sensitive_text(exc)},
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
            {"ok": False, "error": redact_sensitive_text(exc)},
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
    parser.add_argument(
        "--quantity",
        default=None,
        help=(
            "One-shot quantity override for this isolated command. "
            "Does not update the stored rule."
        ),
    )
    parser.add_argument(
        "--limit-price",
        default=None,
        help=(
            "One-shot limit-price override for this isolated command. "
            "Does not update the stored rule."
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
    mode_group.add_argument(
        "--full-path-live-test",
        action="store_true",
        help=(
            "Submit one real order through the same warmed executor, "
            "pre-release reservation, batch-post, and ledger-completion "
            "path as the continuous runner."
        ),
    )
    parser.add_argument(
        "--test-run-id",
        default=None,
        help=(
            "Required stable idempotency id for --full-path-live-test. "
            "Reuse the same value to make an accidental rerun fail "
            "before order submission."
        ),
    )
    parser.add_argument(
        "--confirm-live-order",
        action="store_true",
        help=(
            "Acknowledge that the real GTC limit order can execute "
            "immediately and that any remainder can fill later."
        ),
    )
    parser.add_argument(
        "--cancel-after-test",
        action="store_true",
        help=(
            "Required for --full-path-live-test. Inspect and cancel only "
            "the exact returned order ID, then require a terminal remote "
            "state before reporting success."
        ),
    )
    return parser


def _run_full_path_live_test(
    *,
    args: argparse.Namespace,
    database_url: str,
    database_target: str,
) -> int:
    validation_error = _validate_full_path_live_test_args(args)
    if validation_error is not None:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": False,
                "error": validation_error,
            },
            stream=sys.stderr,
        )
        return 4

    action = str(args.action).upper()
    test_run_id = str(args.test_run_id).strip()
    try:
        quantity = _required_decimal(args.quantity, name="order_qty")
        limit_price = _required_decimal(
            args.limit_price,
            name=f"{action} order price",
        )
    except ValueError as exc:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": False,
                "error": redact_sensitive_text(exc),
            },
            stream=sys.stderr,
        )
        return 4
    if quantity <= 0:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": False,
                "error": "Test quantity must be greater than zero",
            },
            stream=sys.stderr,
        )
        return 4
    if limit_price <= 0 or limit_price >= 1:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": False,
                "error": "Test limit price must be between zero and one",
            },
            stream=sys.stderr,
        )
        return 4

    rule_repository = SqlAlchemyRuleRepository(
        database_url=database_url
    )
    try:
        rules = rule_repository.load_active_cbr_rules()
        stored_rule = _select_rule(rules, rule_id=args.rule_id)
    except (RuleLoadError, ValueError) as exc:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": False,
                "error": redact_sensitive_text(exc),
            },
            stream=sys.stderr,
        )
        return 3
    finally:
        rule_repository.close()

    test_rule = _with_order_overrides(
        stored_rule,
        action=action,
        quantity=quantity,
        limit_price=limit_price,
    )
    test_url = f"cbr-live-test://{test_run_id}"
    safety = LiveSafetySettings.from_env()
    executor = WarmLiveOrderExecutor(
        subscriptions=(test_rule,),
        database_url=database_url,
        safety=safety,
    )
    intent = OrderIntent(
        rule_id=test_rule.get("id"),
        rule_key=str(test_rule.get("rule_key") or "default"),
        account_name=str(test_rule.get("account_name") or ""),
        condition_id=str(test_rule.get("condition_id") or ""),
        action=action,
        quantity=quantity,
        limit_price=limit_price,
        ready=True,
        reason="full_path_live_test",
    )
    release = DiscoveryResult(
        ok=True,
        reason="full_path_live_test",
        url=test_url,
        request_url=test_url,
        title="Manual full-path CBR live test",
        detected_from="full_path_live_test",
    )

    execution_started = False
    try:
        summary = executor.prepare(release_url=test_url)
        execution_started = True
        results = tuple(executor.execute((intent,), release=release))
    except Exception as exc:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": (
                    None if execution_started else False
                ),
                "database_target": database_target,
                "test_run_id": test_run_id,
                "error": _safe_exception(exc),
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        executor.close()

    if len(results) != 1:
        _print_json(
            {
                "ok": False,
                "mode": "full_path_live_test",
                "order_submitted": None,
                "database_target": database_target,
                "test_run_id": test_run_id,
                "error": "Full-path executor returned an invalid result count",
            },
            stream=sys.stderr,
        )
        return 5

    result = results[0]
    cleanup = _unused_live_test_cleanup(result=result)
    if result.order_id:
        cleanup = _cleanup_full_path_test_order(
            database_url=database_url,
            safety=safety,
            account_name=intent.account_name,
            order_id=str(result.order_id),
        )
    elif result.success is True:
        cleanup = {
            **cleanup,
            "confirmed_terminal": False,
            "error": (
                "Accepted test order has no order ID for exact cleanup"
            ),
        }

    succeeded = (
        result.success is True
        and cleanup["confirmed_terminal"] is True
    )
    payload = {
        "ok": succeeded,
        "mode": "full_path_live_test",
        "database_target": database_target,
        "test_run_id": test_run_id,
        "prepared_outcomes": summary.outcome_count,
        "order": {
            "rule_id": intent.rule_id,
            "action": intent.action,
            "quantity": str(quantity),
            "limit_price": str(limit_price),
        },
        "result": {
            "status": result.status,
            "attempted": result.attempted,
            "accepted": result.success,
            "order_id": result.order_id,
            "error": result.error,
        },
        "cleanup": cleanup,
    }
    _print_json(
        payload,
        stream=sys.stdout if succeeded else sys.stderr,
    )
    return 0 if succeeded else 5


def _validate_full_path_live_test_args(
    args: argparse.Namespace,
) -> str | None:
    if not args.confirm_live_order:
        return (
            "--confirm-live-order is required with "
            "--full-path-live-test"
        )
    if not args.cancel_after_test:
        return (
            "--cancel-after-test is required with "
            "--full-path-live-test"
        )
    if args.rule_id is None:
        return "--rule-id is required with --full-path-live-test"
    if not args.action:
        return "--action YES|NO is required with --full-path-live-test"
    if args.quantity is None:
        return "--quantity is required with --full-path-live-test"
    if args.limit_price is None:
        return "--limit-price is required with --full-path-live-test"
    test_run_id = str(args.test_run_id or "").strip()
    if not _LIVE_TEST_ID_PATTERN.fullmatch(test_run_id):
        return (
            "--test-run-id must be 3-64 characters using only "
            "letters, digits, dot, underscore, or dash"
        )
    return None


def _unused_live_test_cleanup(*, result: Any) -> dict[str, Any]:
    no_remote_order = (
        result.success is not True
        and not str(result.order_id or "").strip()
    )
    return {
        "required": True,
        "attempted": False,
        "cancel_requested": False,
        "cancel_acknowledged": False,
        "initial_state": None,
        "final_state": None,
        "confirmed_terminal": no_remote_order,
        "error": None,
    }


def _cleanup_full_path_test_order(
    *,
    database_url: str,
    safety: LiveSafetySettings,
    account_name: str,
    order_id: str,
) -> dict[str, Any]:
    gateway = PolymarketSupervisionOrderGateway(
        database_url=database_url,
        safety=safety,
    )
    initial_state: RemoteOrderState | None = None
    final_state: RemoteOrderState | None = None
    cancel_requested = False
    cancel_acknowledged = False
    failure_types: list[str] = []
    terminal_states = {
        RemoteOrderState.CANCELLED,
        RemoteOrderState.FILLED,
    }
    try:
        try:
            initial = gateway.inspect_orders(
                account_name=account_name,
                order_ids=(order_id,),
            )
            initial_state = _single_inspection_state(initial)
        except Exception as exc:
            failure_types.append(
                "initial inspection " + type(exc).__name__
            )

        final_state = initial_state
        if initial_state not in terminal_states:
            cancel_requested = True
            try:
                cancellation = gateway.cancel_orders(
                    account_name=account_name,
                    order_ids=(order_id,),
                )
                cancel_acknowledged = (
                    order_id in cancellation.cancelled_order_ids
                )
                if not cancel_acknowledged:
                    failure_types.append("cancellation not acknowledged")
            except Exception as exc:
                failure_types.append(
                    "cancellation " + type(exc).__name__
                )

            try:
                final = gateway.inspect_orders(
                    account_name=account_name,
                    order_ids=(order_id,),
                )
                final_state = _single_inspection_state(final)
                if final_state is None:
                    failure_types.append(
                        "final inspection not confirmed"
                    )
            except Exception as exc:
                final_state = None
                failure_types.append(
                    "final inspection " + type(exc).__name__
                )
    finally:
        try:
            gateway.close()
        except Exception as exc:
            failure_types.append("gateway close " + type(exc).__name__)

    confirmed_terminal = final_state in terminal_states
    error = None
    if not confirmed_terminal:
        error = redact_sensitive_text(
            "Exact-order cleanup was not confirmed"
            + (
                ": " + "; ".join(dict.fromkeys(failure_types))
                if failure_types
                else ""
            )
        )
    return {
        "required": True,
        "attempted": True,
        "cancel_requested": cancel_requested,
        "cancel_acknowledged": cancel_acknowledged,
        "initial_state": _remote_state_value(initial_state),
        "final_state": _remote_state_value(final_state),
        "confirmed_terminal": confirmed_terminal,
        "error": error,
    }


def _single_inspection_state(
    inspection: Any,
) -> RemoteOrderState | None:
    snapshots = tuple(inspection.snapshots)
    failed = tuple(inspection.failed_order_ids)
    if failed or len(snapshots) != 1:
        return None
    state = snapshots[0].state
    return (
        state
        if isinstance(state, RemoteOrderState)
        else RemoteOrderState(str(state).upper())
    )


def _remote_state_value(
    state: RemoteOrderState | None,
) -> str | None:
    return state.value if state is not None else None


def _with_order_overrides(
    rule: Mapping[str, Any],
    *,
    action: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> dict[str, Any]:
    overridden = dict(rule)
    overridden["order_qty"] = str(quantity)
    raw_params = rule.get("params")
    params = (
        dict(raw_params)
        if isinstance(raw_params, Mapping)
        else {}
    )
    params[
        "order_price_yes" if action == "YES" else "order_price_no"
    ] = str(limit_price)
    overridden["params"] = params
    return overridden


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
            {"ok": False, "error": redact_sensitive_text(exc)},
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
        summary = executor.prepare(
            release_url=build_predicted_release_url(
                release_date=os.environ.get("BOR_RELEASE_DATE"),
                release_time_suffix=(
                    os.environ.get("BOR_RELEASE_TIME_SUFFIX") or ""
                ),
            ),
            reserve_claims=False,
        )
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
    return redact_exception(exc)


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
