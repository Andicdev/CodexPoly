from __future__ import annotations

import argparse
import json
import os
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
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
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


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)
    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        _print_json(
            {
                "ok": False,
                "mode": "resolution_preflight",
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
        strategy = FixedOutcomeStrategy((rule,))
        signal, context = _manual_preflight_scope(rule)
    except (
        RuleLoadError,
        FixedOutcomeConfigurationError,
        TypeError,
        ValueError,
    ) as exc:
        _print_json(
            {
                "ok": False,
                "mode": "resolution_preflight",
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
    executor = PolymarketPreflightPreparedExecutor(
        database_url=database.url,
        safety=safety,
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
        payload = _preflight_payload(
            rule=rule,
            database_target=database.target,
            safety=safety,
            preparation=preparation,
            outcome=outcome,
            executor=executor,
        )
    except Exception as exc:
        _print_json(
            {
                "ok": False,
                "mode": "resolution_preflight",
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
            "source-neutral fixed-outcome rule. Never submits an order."
        )
    )
    parser.add_argument(
        "--rule-id",
        type=int,
        required=True,
        help="Active monitored_news rule id.",
    )
    return parser


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
