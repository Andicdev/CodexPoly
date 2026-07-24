from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.db_config import resolve_database_selection
from cbr_trading.domain import ResolutionSignal, SignalEvidence
from cbr_trading.execution import (
    PolymarketPreparedExecutor,
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.exact_cleanup import cleanup_exact_order
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.rule_repository import (
    RuleLoadError,
    SqlAlchemyRuleRepository,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import ManualResolutionSource
from cbr_trading.strategies import (
    FixedOutcomeConfigurationError,
    FixedOutcomeStrategy,
)

_LIVE_TEST_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"
)


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)
    validation_error = _validate_live_test_args(args)
    if validation_error is not None:
        _print_json(
            {
                "ok": False,
                "mode": "resolution_live_test",
                "order_submitted": False,
                "error": validation_error,
            },
            stream=sys.stderr,
        )
        return 2
    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        _print_json(
            {
                "ok": False,
                "mode": (
                    "resolution_live_test"
                    if args.live_test
                    else "resolution_preflight"
                ),
                "order_submitted": False,
                "error": (
                    database.error
                    or "Primary database URL is not configured"
                ),
            },
            stream=sys.stderr,
        )
        return 3

    repository = SqlAlchemyRuleRepository(
        database_url=database.url
    )
    try:
        rule = repository.load_active_rule(args.rule_id)
        if args.live_test:
            rule = _with_live_order_overrides(
                rule,
                quantity=args.quantity,
                limit_price=args.limit_price,
            )
        strategy = FixedOutcomeStrategy((rule,))
        signal, context = (
            _manual_live_test_scope(
                rule,
                test_run_id=args.test_run_id,
            )
            if args.live_test
            else _manual_preflight_scope(rule)
        )
    except (
        RuleLoadError,
        FixedOutcomeConfigurationError,
        TypeError,
        ValueError,
    ) as exc:
        _print_json(
            {
                "ok": False,
                "mode": (
                    "resolution_live_test"
                    if args.live_test
                    else "resolution_preflight"
                ),
                "order_submitted": False,
                "error": redact_exception(exc),
            },
            stream=sys.stderr,
        )
        return 3
    finally:
        repository.close()

    source = ManualResolutionSource(
        source_name=signal.source,
        signals=(signal,),
    )
    safety = LiveSafetySettings.from_env()
    executor = (
        PolymarketPreparedExecutor(
            database_url=database.url,
            safety=safety,
        )
        if args.live_test
        else PolymarketPreflightPreparedExecutor(
            database_url=database.url,
            safety=safety,
        )
    )
    coordinator = ResolutionTradingCoordinator(
        source=source,
        strategies=(strategy,),
        executor=executor,
        context=context,
    )
    try:
        preparation = coordinator.prepare()
        outcome = (
            coordinator.poll_once()
            if preparation.ready
            else None
        )
        payload = (
            _live_test_payload(
                rule=rule,
                database_url=database.url,
                database_target=database.target,
                safety=safety,
                preparation=preparation,
                outcome=outcome,
                executor=executor,
                test_run_id=args.test_run_id,
            )
            if args.live_test
            else _preflight_payload(
                rule=rule,
                database_target=database.target,
                safety=safety,
                preparation=preparation,
                outcome=outcome,
                executor=executor,
            )
        )
    except Exception as exc:
        _print_json(
            {
                "ok": False,
                "mode": (
                    "resolution_live_test"
                    if args.live_test
                    else "resolution_preflight"
                ),
                "order_submitted": False,
                "error": redact_exception(exc),
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        try:
            coordinator.close()
        except Exception:
            pass

    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Authenticate, refresh the book, pre-sign, and dry-run one "
            "source-neutral fixed-outcome rule. Submission requires every "
            "explicit live-test guard."
        )
    )
    parser.add_argument(
        "--rule-id",
        type=int,
        required=True,
        help="Active monitored_news rule id.",
    )
    parser.add_argument(
        "--live-test",
        action="store_true",
        help=(
            "Submit one controlled order, then inspect and cancel only "
            "its exact order ID."
        ),
    )
    parser.add_argument(
        "--test-run-id",
        help="Unique idempotency scope for one controlled live test.",
    )
    parser.add_argument(
        "--quantity",
        type=Decimal,
        help="One-shot live-test share quantity; the database is unchanged.",
    )
    parser.add_argument(
        "--limit-price",
        type=Decimal,
        help="One-shot live-test limit price; the database is unchanged.",
    )
    parser.add_argument(
        "--confirm-live-order",
        action="store_true",
        help="Required acknowledgement for --live-test.",
    )
    parser.add_argument(
        "--cancel-after-test",
        action="store_true",
        help="Required exact-order cleanup opt-in for --live-test.",
    )
    return parser


def _validate_live_test_args(
    args: argparse.Namespace,
) -> str | None:
    live_values_present = any(
        (
            args.test_run_id,
            args.quantity is not None,
            args.limit_price is not None,
            args.confirm_live_order,
            args.cancel_after_test,
        )
    )
    if not args.live_test:
        if live_values_present:
            return "Live-test options require --live-test"
        return None
    if not args.confirm_live_order:
        return "--confirm-live-order is required with --live-test"
    if not args.cancel_after_test:
        return "--cancel-after-test is required with --live-test"
    test_run_id = str(args.test_run_id or "").strip()
    if not _LIVE_TEST_ID_PATTERN.fullmatch(test_run_id):
        return (
            "--test-run-id must be 3-64 characters using only "
            "letters, digits, dot, underscore, or dash"
        )
    if args.quantity is None:
        return "--quantity is required with --live-test"
    if not args.quantity.is_finite() or args.quantity <= 0:
        return "--quantity must be a positive finite decimal"
    if args.limit_price is None:
        return "--limit-price is required with --live-test"
    if (
        not args.limit_price.is_finite()
        or args.limit_price <= 0
        or args.limit_price >= 1
    ):
        return "--limit-price must be between 0 and 1"
    return None


def _manual_preflight_scope(
    rule: Mapping[str, Any],
) -> tuple[ResolutionSignal, PreparationContext]:
    params = rule.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("Rule params are invalid")
    rule_id = int(rule["id"])
    source = _required_text(params.get("source"), "source")
    subject = _required_text(params.get("subject"), "subject")
    metric = _required_text(params.get("metric"), "metric")
    if "signal_value" not in params:
        raise ValueError("Rule signal_value is missing")
    signal_value = _signal_value(params["signal_value"])
    scope_id = f"manual-preflight:rule:{rule_id}"
    reference = f"manual://resolution-rule/{rule_id}"
    detected_at = datetime.now(timezone.utc)
    signal = ResolutionSignal(
        signal_id=scope_id,
        source=source,
        subject=subject,
        metric=metric,
        value=signal_value,
        detected_at=detected_at,
        evidence=(
            SignalEvidence(
                source_url=reference,
                title="Controlled source-neutral preflight signal",
            ),
        ),
        attributes={
            "manual_preflight": True,
            "rule_id": rule_id,
        },
    )
    context = PreparationContext(
        scope_id=scope_id,
        source=source,
        source_reference=reference,
        attributes={
            "manual_preflight": True,
            "rule_id": rule_id,
        },
    )
    return signal, context


def _manual_live_test_scope(
    rule: Mapping[str, Any],
    *,
    test_run_id: str,
) -> tuple[ResolutionSignal, PreparationContext]:
    params = rule.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("Rule params are invalid")
    rule_id = int(rule["id"])
    source = _required_text(params.get("source"), "source")
    subject = _required_text(params.get("subject"), "subject")
    metric = _required_text(params.get("metric"), "metric")
    if "signal_value" not in params:
        raise ValueError("Rule signal_value is missing")
    normalized_run_id = str(test_run_id or "").strip()
    scope_id = (
        f"manual-live-test:{normalized_run_id}:rule:{rule_id}"
    )
    reference = f"manual://resolution-live-test/{normalized_run_id}"
    detected_at = datetime.now(timezone.utc)
    attributes = {
        "manual_live_test": True,
        "rule_id": rule_id,
        "test_run_id": normalized_run_id,
    }
    signal = ResolutionSignal(
        signal_id=scope_id,
        source=source,
        subject=subject,
        metric=metric,
        value=_signal_value(params["signal_value"]),
        detected_at=detected_at,
        evidence=(
            SignalEvidence(
                source_url=reference,
                title="Controlled source-neutral live-test signal",
            ),
        ),
        attributes=attributes,
    )
    context = PreparationContext(
        scope_id=scope_id,
        source=source,
        source_reference=reference,
        attributes=attributes,
    )
    return signal, context


def _with_live_order_overrides(
    rule: Mapping[str, Any],
    *,
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
    outcome = str(params.get("action") or "").strip().lower()
    if outcome not in {"yes", "no"}:
        raise ValueError("Rule action is invalid")
    params[f"order_price_{outcome}"] = str(limit_price)
    overridden["params"] = params
    return overridden


def _preflight_payload(
    *,
    rule: Mapping[str, Any],
    database_target: str,
    safety: LiveSafetySettings,
    preparation: Any,
    outcome: Any,
    executor: PolymarketPreflightPreparedExecutor,
) -> dict[str, Any]:
    completed = (
        outcome is not None
        and outcome.status == CoordinationStatus.COMPLETED
    )
    dry_run_results = (
        completed
        and bool(outcome.order_results)
        and all(
            result.status.value == "DRY_RUN"
            and result.attempted is False
            for result in outcome.order_results
        )
    )
    ready = preparation.ready and completed and dry_run_results
    return {
        "ok": ready,
        "mode": "resolution_preflight",
        "order_submitted": False,
        "database_target": database_target,
        "rule": {
            "id": rule.get("id"),
            "type": rule.get("type"),
            "ticker": rule.get("ticker"),
            "rule_key": rule.get("rule_key"),
            "account_name": rule.get("account_name"),
            "condition_id": rule.get("condition_id"),
            "question": rule.get("question"),
        },
        "preparation": {
            "ready": preparation.ready,
            "error": preparation.error,
            "maximum_notional": str(
                executor.maximum_notional
            ),
            "items": [
                {
                    "template_id": item.template_id,
                    "status": item.status.value,
                    "error": item.error,
                }
                for item in preparation.summary.items
            ],
        },
        "market": [
            {
                "template_id": detail.template_id,
                "outcome": detail.outcome,
                "token_id": detail.token_id,
                "quantity": str(detail.quantity),
                "desired_price": str(detail.desired_price),
                "effective_price": str(detail.effective_price),
                "tick_size": str(detail.tick_size),
                "minimum_order_size": str(
                    detail.minimum_order_size
                ),
                "best_bid": _decimal_or_none(detail.best_bid),
                "best_ask": _decimal_or_none(detail.best_ask),
                "order_presigned": detail.order_presigned,
                "collateral_sufficient": (
                    detail.collateral_sufficient
                ),
            }
            for detail in executor.details
        ],
        "manual_signal": {
            "selected_intents": (
                len(outcome.intents)
                if outcome is not None
                else 0
            ),
            "status": (
                outcome.status.value
                if outcome is not None
                else None
            ),
            "results": (
                [
                    {
                        "template_id": result.intent.template_id,
                        "outcome": result.intent.outcome.value,
                        "status": result.status.value,
                        "attempted": result.attempted,
                    }
                    for result in outcome.order_results
                ]
                if outcome is not None
                else []
            ),
        },
        "safety": {
            "live_trading_enabled": safety.trading_enabled,
            "post_only": safety.post_only,
            "allowed_account_present": bool(
                safety.allowed_account
            ),
            "max_order_quantity_present": (
                safety.max_order_quantity is not None
            ),
            "max_notional_present": (
                safety.max_notional is not None
            ),
            "max_total_notional_present": (
                safety.max_total_notional is not None
            ),
            "master_key_present": bool(
                safety.accounts_master_key
            ),
        },
    }


def _live_test_payload(
    *,
    rule: Mapping[str, Any],
    database_url: str,
    database_target: str,
    safety: LiveSafetySettings,
    preparation: Any,
    outcome: Any,
    executor: PolymarketPreparedExecutor,
    test_run_id: str,
) -> dict[str, Any]:
    completed = (
        outcome is not None
        and outcome.status == CoordinationStatus.COMPLETED
    )
    results = (
        tuple(outcome.order_results)
        if completed
        else ()
    )
    result = results[0] if len(results) == 1 else None
    known_orders = (
        tuple(result.orders)
        if result is not None
        else ()
    )
    cleanup: dict[str, Any] = {
        "required": True,
        "attempted": False,
        "order_id": None,
        "cancel_requested": False,
        "cancel_acknowledged": False,
        "initial_state": None,
        "final_state": None,
        "confirmed_terminal": False,
        "audit_recorded": False,
        "audit_error": None,
        "error": None,
    }
    if len(known_orders) == 1 and result is not None:
        order = known_orders[0]
        try:
            cleanup = {
                **cleanup_exact_order(
                    database_url=database_url,
                    safety=safety,
                    account_name=result.intent.account_name,
                    order_id=order.order_id,
                ),
                "audit_recorded": False,
                "audit_error": None,
            }
        except Exception as exc:
            cleanup = {
                **cleanup,
                "attempted": True,
                "order_id": order.order_id,
                "error": redact_exception(exc),
            }
        try:
            executor.record_cleanup(
                template_id=result.intent.template_id,
                cleanup={
                    key: value
                    for key, value in cleanup.items()
                    if not key.startswith("audit_")
                },
            )
            cleanup["audit_recorded"] = True
        except Exception as exc:
            cleanup["audit_error"] = redact_exception(exc)
    elif result is not None and (
        result.status.value == "REJECTED"
    ):
        cleanup["confirmed_terminal"] = True
    elif len(known_orders) > 1:
        cleanup["error"] = (
            "Controlled live test returned more than one order"
        )
    else:
        cleanup["error"] = (
            "No exact order ID is available to confirm cleanup"
        )

    submitted = (
        result is not None
        and result.status.value == "SUBMITTED"
        and len(known_orders) == 1
    )
    succeeded = (
        preparation.ready
        and completed
        and submitted
        and cleanup["confirmed_terminal"] is True
        and cleanup["audit_recorded"] is True
    )
    return {
        "ok": succeeded,
        "mode": "resolution_live_test",
        "test_run_id": test_run_id,
        "order_submitted": bool(known_orders),
        "database_target": database_target,
        "rule": {
            "id": rule.get("id"),
            "type": rule.get("type"),
            "ticker": rule.get("ticker"),
            "rule_key": rule.get("rule_key"),
            "account_name": rule.get("account_name"),
            "condition_id": rule.get("condition_id"),
            "question": rule.get("question"),
        },
        "preparation": {
            "ready": preparation.ready,
            "error": preparation.error,
            "maximum_notional": str(
                executor.maximum_notional
            ),
            "items": [
                {
                    "template_id": item.template_id,
                    "status": item.status.value,
                    "error": item.error,
                }
                for item in preparation.summary.items
            ],
        },
        "market": [
            {
                "template_id": detail.template_id,
                "outcome": detail.outcome,
                "token_id": detail.token_id,
                "quantity": str(detail.quantity),
                "desired_price": str(detail.desired_price),
                "effective_price": str(detail.effective_price),
                "tick_size": str(detail.tick_size),
                "minimum_order_size": str(
                    detail.minimum_order_size
                ),
                "best_bid": _decimal_or_none(detail.best_bid),
                "best_ask": _decimal_or_none(detail.best_ask),
                "order_presigned": detail.order_presigned,
            }
            for detail in executor.details
        ],
        "manual_signal": {
            "selected_intents": (
                len(outcome.intents)
                if outcome is not None
                else 0
            ),
            "status": (
                outcome.status.value
                if outcome is not None
                else None
            ),
            "results": (
                [
                    {
                        "template_id": item.intent.template_id,
                        "outcome": item.intent.outcome.value,
                        "status": item.status.value,
                        "attempted": item.attempted,
                        "order_ids": [
                            order.order_id
                            for order in item.orders
                        ],
                        "error": item.error,
                    }
                    for item in results
                ]
            ),
        },
        "cleanup": cleanup,
        "safety": {
            "live_trading_enabled": safety.trading_enabled,
            "post_only": safety.post_only,
            "allowed_account_present": bool(
                safety.allowed_account
            ),
            "max_order_quantity_present": (
                safety.max_order_quantity is not None
            ),
            "max_notional_present": (
                safety.max_notional is not None
            ),
            "max_total_notional_present": (
                safety.max_total_notional is not None
            ),
            "master_key_present": bool(
                safety.accounts_master_key
            ),
        },
    }


def _signal_value(value: Any) -> Decimal | str | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    if isinstance(value, (int, float, Decimal)):
        parsed = Decimal(str(value))
        if parsed.is_finite():
            return parsed
    raise ValueError("Rule signal_value is invalid")


def _required_text(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Rule {name} is missing")
    return normalized


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


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
