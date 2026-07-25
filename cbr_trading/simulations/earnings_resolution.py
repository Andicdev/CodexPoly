from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.db_config import resolve_database_selection
from cbr_trading.domain import (
    OrderSide,
    OrderTemplate,
    Outcome,
    RepriceOnTickChange,
)
from cbr_trading.earnings import (
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsProvider,
    EpsBasis,
    SourceAuthority,
    SqlAlchemyEarningsStore,
)
from cbr_trading.execution import (
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources.earnings import (
    EARNINGS_NON_GAAP_EPS_METRIC,
    EARNINGS_SOURCE_NAME,
    EarningsResolutionSource,
)
from cbr_trading.strategies import (
    NUMERIC_THRESHOLD_STRATEGY_ID,
    NumericThresholdRule,
    NumericThresholdStrategy,
)


_RUN_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"
)


class SyntheticScopedEarningsSource:
    """Keep a synthetic signal outside the production idempotency scope."""

    source_name = EARNINGS_SOURCE_NAME

    def __init__(
        self,
        *,
        inner: EarningsResolutionSource,
        simulation_scope_id: str,
    ):
        self._inner = inner
        self._simulation_scope_id = simulation_scope_id

    def poll_once(self) -> tuple[Any, ...]:
        return tuple(
            replace(
                signal,
                signal_id=self._simulation_scope_id,
                attributes={
                    **signal.attributes,
                    "synthetic": True,
                    "parser_bypassed": True,
                    "production_scope_id": signal.signal_id,
                },
            )
            for signal in self._inner.poll_once()
        )

    def close(self) -> None:
        self._inner.close()


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)
    validation_error = _validate_args(args)
    if validation_error is not None:
        _print_json(
            _error_payload(validation_error),
            stream=sys.stderr,
        )
        return 2

    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        _print_json(
            _error_payload(
                database.error
                or "Primary database URL is not configured"
            ),
            stream=sys.stderr,
        )
        return 3

    run_id = args.run_id or f"sim-{uuid.uuid4().hex[:12]}"
    store = SqlAlchemyEarningsStore(database_url=database.url)
    coordinator: ResolutionTradingCoordinator | None = None
    try:
        store.ensure_ready()
        rule = _select_rule(
            store.load_active_rules(),
            ticker=args.ticker,
            fiscal_year=args.fiscal_year,
            fiscal_quarter=args.fiscal_quarter,
        )
        if not rule.condition_id:
            raise ValueError(
                "earnings rule has no Polymarket condition_id"
            )

        safety = LiveSafetySettings.from_env()
        account_name = str(safety.allowed_account or "").strip()
        if not account_name:
            raise ValueError("allowed trading account is not configured")

        now = datetime.now(timezone.utc)
        normalized_eps = _round(args.eps, rule.rounding_places)
        candidate = _synthetic_fact(
            rule=rule,
            raw_eps=args.eps,
            normalized_eps=normalized_eps,
            run_id=run_id,
            now=now,
        )
        simulation_scope_id = (
            f"simulation:{rule.scope_id}:{run_id}"
        )
        source_reference = (
            f"https://synthetic.invalid/codexpoly/earnings/{run_id}"
        )
        source = SyntheticScopedEarningsSource(
            inner=EarningsResolutionSource(
                candidate_provider=lambda: (candidate,),
                rules=(rule,),
            ),
            simulation_scope_id=simulation_scope_id,
        )
        yes_template, no_template = _order_templates(
            rule=rule,
            account_name=account_name,
            quantity=args.quantity,
            limit_price=args.limit_price,
        )
        strategy = NumericThresholdStrategy(
            (
                NumericThresholdRule(
                    rule_key=rule.rule_key,
                    source=EARNINGS_SOURCE_NAME,
                    subject=_signal_subject(rule),
                    metric=_signal_metric(rule),
                    comparison_op=rule.comparison_op,
                    strike=rule.strike,
                    rounding_places=rule.rounding_places,
                    yes_template=yes_template,
                    no_template=no_template,
                ),
            )
        )
        context = PreparationContext(
            scope_id=simulation_scope_id,
            source=EARNINGS_SOURCE_NAME,
            source_reference=source_reference,
            attributes={
                "synthetic": True,
                "parser_bypassed": True,
                "production_scope_id": rule.scope_id,
                "run_id": run_id,
            },
        )
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
        preparation = coordinator.prepare()
        outcome = (
            coordinator.poll_once()
            if preparation.ready
            else None
        )
        payload = _result_payload(
            database_target=database.target,
            rule=rule,
            run_id=run_id,
            raw_eps=args.eps,
            normalized_eps=normalized_eps,
            safety=safety,
            preparation=preparation,
            outcome=outcome,
            executor=executor,
        )
    except Exception as exc:
        _print_json(
            _error_payload(redact_exception(exc)),
            stream=sys.stderr,
        )
        return 5
    finally:
        if coordinator is not None:
            try:
                coordinator.close()
            except Exception:
                pass
        store.close()

    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inject one normalized synthetic earnings fact, run the real "
            "earnings source, numeric strategy, and authenticated "
            "PreparedExecutor preflight, and never submit an order."
        )
    )
    parser.add_argument("--ticker", default="NVTS")
    parser.add_argument("--fiscal-year", type=int, default=2026)
    parser.add_argument("--fiscal-quarter", type=int, default=2)
    parser.add_argument(
        "--eps",
        type=Decimal,
        required=True,
        help="Synthetic normalized EPS value injected after parsing.",
    )
    parser.add_argument(
        "--quantity",
        type=Decimal,
        default=Decimal("5"),
        help="Share quantity used only for executor preflight.",
    )
    parser.add_argument(
        "--limit-price",
        type=Decimal,
        default=Decimal("0.10"),
        help="Post-only candidate price used only for executor preflight.",
    )
    parser.add_argument(
        "--run-id",
        help="Unique synthetic run id; generated automatically when omitted.",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> str | None:
    if args.fiscal_quarter not in {1, 2, 3, 4}:
        return "fiscal quarter must be between 1 and 4"
    if not args.eps.is_finite():
        return "EPS must be finite"
    if args.quantity <= 0:
        return "quantity must be positive"
    if args.limit_price <= 0 or args.limit_price >= 1:
        return "limit price must be greater than 0 and less than 1"
    if args.run_id and not _RUN_ID_PATTERN.fullmatch(args.run_id):
        return "run id must be 3-64 safe characters"
    return None


def _select_rule(
    rules: Sequence[EarningsMarketRule],
    *,
    ticker: str,
    fiscal_year: int,
    fiscal_quarter: int,
) -> EarningsMarketRule:
    normalized_ticker = str(ticker or "").strip().upper()
    matches = tuple(
        rule
        for rule in rules
        if (
            rule.ticker == normalized_ticker
            and rule.fiscal_year == fiscal_year
            and rule.fiscal_quarter == fiscal_quarter
        )
    )
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one active earnings rule for simulation"
        )
    return matches[0]


def _synthetic_fact(
    *,
    rule: EarningsMarketRule,
    raw_eps: Decimal,
    normalized_eps: Decimal,
    run_id: str,
    now: datetime,
) -> EarningsFactCandidate:
    source_url = (
        f"https://synthetic.invalid/codexpoly/earnings/{run_id}"
    )
    fingerprint = hashlib.sha256(
        (
            f"{run_id}|{rule.scope_id}|{raw_eps}|"
            f"{normalized_eps}"
        ).encode("utf-8")
    ).hexdigest()
    return EarningsFactCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"synthetic-{run_id}",
        ticker=rule.ticker,
        cik=rule.cik,
        period_end=rule.period_end,
        metric=rule.metric,
        basis=(
            EpsBasis.BASIC_AND_DILUTED
            if rule.primary_basis is EpsBasis.DILUTED
            else rule.primary_basis
        ),
        currency=rule.currency,
        raw_value=raw_eps,
        value=normalized_eps,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        source_url=source_url,
        filing_url=source_url,
        published_at=now,
        detected_at=now,
        parser_name="synthetic_parser_bypass",
        parser_version="1",
        confidence=Decimal("1"),
        document_fingerprint=fingerprint,
        evidence_title="Synthetic earnings resolution test fact",
        excerpt="Synthetic normalized EPS; parser intentionally bypassed.",
        attributes={
            "synthetic": True,
            "parser_bypassed": True,
        },
    )


def _order_templates(
    *,
    rule: EarningsMarketRule,
    account_name: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> tuple[OrderTemplate, OrderTemplate]:
    if not rule.condition_id:
        raise ValueError("condition_id is required")
    common = {
        "strategy_id": NUMERIC_THRESHOLD_STRATEGY_ID,
        "account_name": account_name,
        "condition_id": rule.condition_id,
        "side": OrderSide.BUY,
        "desired_price": limit_price,
        "quantity": quantity,
        "lifecycle_policy": RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            max_reprices=1,
        ),
        "metadata": {
            "rule_key": rule.rule_key,
            "production_scope_id": rule.scope_id,
            "synthetic": True,
        },
    }
    prefix = f"numeric-threshold:{rule.rule_key}"
    return (
        OrderTemplate(
            template_id=f"{prefix}:YES",
            outcome=Outcome.YES,
            **common,
        ),
        OrderTemplate(
            template_id=f"{prefix}:NO",
            outcome=Outcome.NO,
            **common,
        ),
    )


def _signal_subject(rule: EarningsMarketRule) -> str:
    return (
        f"company:{rule.ticker}:earnings:"
        f"{rule.fiscal_year}Q{rule.fiscal_quarter}"
    )


def _signal_metric(rule: EarningsMarketRule) -> str:
    return (
        EARNINGS_NON_GAAP_EPS_METRIC
        if rule.metric is EarningsMetric.NON_GAAP_EPS
        else "company.earnings.eps.gaap"
    )


def _round(value: Decimal, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _expected_outcome(
    *,
    value: Decimal,
    operation: str,
    strike: Decimal,
) -> Outcome:
    if operation == ">":
        resolved_yes = value > strike
    elif operation == ">=":
        resolved_yes = value >= strike
    elif operation == "<":
        resolved_yes = value < strike
    elif operation == "<=":
        resolved_yes = value <= strike
    elif operation == "==":
        resolved_yes = value == strike
    else:
        raise ValueError("unsupported comparison operation")
    return Outcome.YES if resolved_yes else Outcome.NO


def _result_payload(
    *,
    database_target: str,
    rule: EarningsMarketRule,
    run_id: str,
    raw_eps: Decimal,
    normalized_eps: Decimal,
    safety: LiveSafetySettings,
    preparation: Any,
    outcome: Any,
    executor: PolymarketPreflightPreparedExecutor,
) -> dict[str, Any]:
    expected = _expected_outcome(
        value=normalized_eps,
        operation=rule.comparison_op,
        strike=_round(rule.strike, rule.rounding_places),
    )
    completed = (
        outcome is not None
        and outcome.status is CoordinationStatus.COMPLETED
    )
    results = (
        tuple(outcome.order_results)
        if completed
        else ()
    )
    selected_outcomes = tuple(
        result.intent.outcome
        for result in results
    )
    dry_run_ok = (
        len(results) == 1
        and results[0].status.value == "DRY_RUN"
        and results[0].attempted is False
        and selected_outcomes == (expected,)
    )
    return {
        "ok": preparation.ready and completed and dry_run_ok,
        "mode": "earnings_resolution_preflight",
        "parser_bypassed": True,
        "synthetic_fact_persisted": False,
        "order_submitted": False,
        "database_target": database_target,
        "simulation": {
            "run_id": run_id,
            "ticker": rule.ticker,
            "fiscal_period": (
                f"{rule.fiscal_year}Q{rule.fiscal_quarter}"
            ),
            "production_scope_id": rule.scope_id,
            "raw_eps": str(raw_eps),
            "normalized_eps": str(normalized_eps),
            "comparison": rule.comparison_op,
            "strike": str(rule.strike),
            "expected_outcome": expected.value,
        },
        "preparation": {
            "ready": preparation.ready,
            "error": preparation.error,
            "maximum_notional": str(executor.maximum_notional),
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
        "resolution": {
            "status": (
                outcome.status.value
                if outcome is not None
                else None
            ),
            "observed_signals": (
                len(outcome.observed_signals)
                if outcome is not None
                else 0
            ),
            "selected_intents": (
                len(outcome.intents)
                if outcome is not None
                else 0
            ),
            "selected_outcome": (
                selected_outcomes[0].value
                if len(selected_outcomes) == 1
                else None
            ),
            "results": [
                {
                    "template_id": result.intent.template_id,
                    "outcome": result.intent.outcome.value,
                    "status": result.status.value,
                    "attempted": result.attempted,
                }
                for result in results
            ],
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


def _error_payload(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": "earnings_resolution_preflight",
        "parser_bypassed": True,
        "synthetic_fact_persisted": False,
        "order_submitted": False,
        "error": error,
    }


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


if __name__ == "__main__":
    raise SystemExit(main())
