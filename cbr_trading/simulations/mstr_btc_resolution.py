from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import (
    ExecutionStatus,
    Outcome,
    RepriceOnTickChange,
)
from cbr_trading.execution import (
    DryRunPreparedExecutor,
    PreparationContext,
)
from cbr_trading.mstr_btc import (
    MSTR_PURCHASE_ANY_SIGNAL_ID,
    MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
    MSTR_SALE_ANY_SIGNAL_ID,
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcResolutionRule,
    MstrBtcValueDerivation,
    mstr_jul21_27_resolution_rules,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    order_templates_from_profile,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import (
    MSTR_BTC_SOURCE_NAME,
    MstrBtcResolutionSource,
    mstr_btc_signal_metric,
    mstr_btc_signal_subject,
)
from cbr_trading.strategies import (
    NUMERIC_THRESHOLD_STRATEGY_ID,
    NumericThresholdRule,
    NumericThresholdStrategy,
)


_RUN_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"
)
_DEFAULT_ACCOUNT_NAME = "abccbaq"
_DEFAULT_DESIRED_PRICE = Decimal("0.999")
_DEFAULT_QUANTITY = Decimal("50")
_BASELINE_HOLDINGS_BTC = 843_775
_PUBLISHED_AT = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
_DETECTED_AT = datetime(
    2026,
    7,
    27,
    12,
    0,
    2,
    tzinfo=timezone.utc,
)


@dataclass(frozen=True)
class MstrBtcDryRunScenario:
    """One parser-bypassed fact and its independently expected outcomes."""

    name: str
    acquired_btc: int | None
    sold_btc: int | None
    net_change_btc: int
    acquired_derivation: MstrBtcValueDerivation
    sold_derivation: MstrBtcValueDerivation
    expected_outcomes: Mapping[str, Outcome]

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("scenario name is required")
        object.__setattr__(self, "name", name)
        outcomes = dict(self.expected_outcomes)
        expected_ids = {
            MSTR_PURCHASE_ANY_SIGNAL_ID,
            MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
            MSTR_SALE_ANY_SIGNAL_ID,
        }
        if set(outcomes) != expected_ids:
            raise ValueError(
                "scenario must define all three expected outcomes"
            )
        if any(not isinstance(value, Outcome) for value in outcomes.values()):
            raise TypeError("expected outcomes must contain Outcome values")
        object.__setattr__(
            self,
            "expected_outcomes",
            MappingProxyType(outcomes),
        )


class SyntheticScopedMstrBtcSource:
    """Keep dry-run signals outside production idempotency scopes."""

    source_name = MSTR_BTC_SOURCE_NAME

    def __init__(
        self,
        *,
        inner: MstrBtcResolutionSource,
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
                    "production_signal_id": signal.signal_id,
                },
            )
            for signal in self._inner.poll_once()
        )

    def close(self) -> None:
        self._inner.close()


def default_mstr_btc_dry_run_scenarios(
) -> tuple[MstrBtcDryRunScenario, ...]:
    """Cover positive, negative, and strict-boundary market decisions."""

    return (
        MstrBtcDryRunScenario(
            name="purchase_over_1000",
            acquired_btc=1_500,
            sold_btc=None,
            net_change_btc=1_500,
            acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
            sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
            expected_outcomes={
                MSTR_PURCHASE_ANY_SIGNAL_ID: Outcome.YES,
                MSTR_PURCHASE_OVER_1000_SIGNAL_ID: Outcome.YES,
                MSTR_SALE_ANY_SIGNAL_ID: Outcome.NO,
            },
        ),
        MstrBtcDryRunScenario(
            name="purchase_exactly_1000",
            acquired_btc=1_000,
            sold_btc=None,
            net_change_btc=1_000,
            acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
            sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
            expected_outcomes={
                MSTR_PURCHASE_ANY_SIGNAL_ID: Outcome.YES,
                MSTR_PURCHASE_OVER_1000_SIGNAL_ID: Outcome.NO,
                MSTR_SALE_ANY_SIGNAL_ID: Outcome.NO,
            },
        ),
        MstrBtcDryRunScenario(
            name="sale",
            acquired_btc=None,
            sold_btc=32,
            net_change_btc=-32,
            acquired_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
            sold_derivation=MstrBtcValueDerivation.EXPLICIT,
            expected_outcomes={
                MSTR_PURCHASE_ANY_SIGNAL_ID: Outcome.NO,
                MSTR_PURCHASE_OVER_1000_SIGNAL_ID: Outcome.NO,
                MSTR_SALE_ANY_SIGNAL_ID: Outcome.YES,
            },
        ),
    )


def run_mstr_btc_dry_run(
    *,
    run_id: str,
    scenarios: Sequence[MstrBtcDryRunScenario] | None = None,
) -> dict[str, Any]:
    """Run three market-scoped coordinators without persistence or signing."""

    if not _RUN_ID_PATTERN.fullmatch(str(run_id or "")):
        raise ValueError("run id must contain 3-64 safe characters")
    selected = tuple(scenarios or default_mstr_btc_dry_run_scenarios())
    if not selected:
        raise ValueError("at least one scenario is required")
    if any(not isinstance(row, MstrBtcDryRunScenario) for row in selected):
        raise TypeError(
            "scenarios must contain MstrBtcDryRunScenario objects"
        )

    rules = mstr_jul21_27_resolution_rules()
    reports: list[dict[str, Any]] = []
    for scenario in selected:
        fact = _synthetic_fact(scenario=scenario, run_id=run_id)
        market_reports = tuple(
            _run_market(
                scenario=scenario,
                fact=fact,
                rule=rule,
                run_id=run_id,
            )
            for rule in rules
        )
        reports.append(
            {
                "name": scenario.name,
                "ok": all(row["ok"] for row in market_reports),
                "fact": {
                    "acquired_btc": scenario.acquired_btc,
                    "sold_btc": scenario.sold_btc,
                    "net_change_btc": scenario.net_change_btc,
                },
                "markets": market_reports,
            }
        )

    decision_count = sum(len(row["markets"]) for row in reports)
    return {
        "ok": all(row["ok"] for row in reports),
        "mode": "mstr_btc_resolution_dry_run",
        "run_id": run_id,
        "parser_bypassed": True,
        "database_used": False,
        "profile_persisted": False,
        "production_scope_claimed": False,
        "order_submitted": False,
        "path": [
            "MstrBtcResolutionSource",
            "ResolutionSignal",
            "NumericThresholdStrategy",
            "OrderIntent",
            "DryRunPreparedExecutor",
        ],
        "scenario_count": len(reports),
        "market_decision_count": decision_count,
        "scenarios": tuple(reports),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_id = args.run_id or f"sim-{uuid.uuid4().hex[:12]}"
    try:
        payload = run_mstr_btc_dry_run(run_id=run_id)
    except Exception as exc:
        payload = {
            "ok": False,
            "mode": "mstr_btc_resolution_dry_run",
            "error": redact_exception(exc),
            "order_submitted": False,
        }
    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run parser-bypassed MSTR BTC facts through three isolated "
            "numeric strategies and DryRunPreparedExecutor instances. "
            "The command uses no database, trading account key, or network."
        )
    )
    parser.add_argument(
        "--run-id",
        help="Unique safe run id; generated automatically when omitted.",
    )
    return parser


def _synthetic_fact(
    *,
    scenario: MstrBtcDryRunScenario,
    run_id: str,
) -> MstrBtcFactCandidate:
    fingerprint = hashlib.sha256(
        f"mstr-dry-run:{run_id}:{scenario.name}".encode("utf-8")
    ).hexdigest()
    return MstrBtcFactCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id=f"synthetic-{run_id}-{scenario.name}",
        baseline_state_id=f"synthetic-baseline-{run_id}",
        holdings_before_btc=_BASELINE_HOLDINGS_BTC,
        holdings_after_btc=(
            _BASELINE_HOLDINGS_BTC + scenario.net_change_btc
        ),
        net_change_btc=scenario.net_change_btc,
        acquired_btc=scenario.acquired_btc,
        sold_btc=scenario.sold_btc,
        acquired_derivation=scenario.acquired_derivation,
        sold_derivation=scenario.sold_derivation,
        holdings_crosscheck_difference_btc=0,
        source_url=(
            "https://synthetic.invalid/codexpoly/mstr-btc/"
            f"{run_id}/{scenario.name}"
        ),
        filing_url=(
            "https://synthetic.invalid/codexpoly/mstr-btc/"
            f"{run_id}/{scenario.name}/filing"
        ),
        published_at=_PUBLISHED_AT,
        detected_at=_DETECTED_AT,
        parser_name="synthetic_parser_bypass",
        parser_version="1",
        document_fingerprint=fingerprint,
        evidence_excerpts=(
            "Synthetic holdings-first fact; parser bypassed.",
        ),
        attributes={
            "ticker": "MSTR",
            "cik": "1050446",
            "synthetic": True,
            "parser_bypassed": True,
        },
    )


def _run_market(
    *,
    scenario: MstrBtcDryRunScenario,
    fact: MstrBtcFactCandidate,
    rule: MstrBtcResolutionRule,
    run_id: str,
) -> dict[str, Any]:
    simulation_scope_id = (
        f"simulation:{rule.signal_id}:{run_id}:{scenario.name}"
    )
    profile = _synthetic_profile(
        rule=rule,
        run_id=run_id,
        scenario_name=scenario.name,
        simulation_scope_id=simulation_scope_id,
    )
    yes_template, no_template = order_templates_from_profile(
        profile,
        strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
        metadata={
            "synthetic": True,
            "parser_bypassed": True,
            "production_signal_id": rule.signal_id,
            "rule_key": rule.rule_key,
        },
    )
    strategy = NumericThresholdStrategy(
        (
            NumericThresholdRule(
                rule_key=rule.rule_key,
                source=MSTR_BTC_SOURCE_NAME,
                subject=mstr_btc_signal_subject(rule.weekly_scope_id),
                metric=mstr_btc_signal_metric(rule.activity),
                comparison_op=rule.comparison_op,
                strike=rule.threshold_btc,
                rounding_places=0,
                yes_template=yes_template,
                no_template=no_template,
            ),
        )
    )
    source = SyntheticScopedMstrBtcSource(
        inner=MstrBtcResolutionSource(
            candidate_provider=lambda: (fact,),
            rules=(rule,),
        ),
        simulation_scope_id=simulation_scope_id,
    )
    coordinator = ResolutionTradingCoordinator(
        source=source,
        strategies=(strategy,),
        executor=DryRunPreparedExecutor(),
        context=PreparationContext(
            scope_id=simulation_scope_id,
            source=MSTR_BTC_SOURCE_NAME,
            source_reference=profile.source_reference,
            attributes={
                "synthetic": True,
                "parser_bypassed": True,
                "production_signal_id": rule.signal_id,
                "scenario": scenario.name,
            },
        ),
    )
    try:
        preparation = coordinator.prepare()
        outcome = coordinator.poll_once() if preparation.ready else None
    finally:
        coordinator.close()

    intents = tuple(outcome.intents) if outcome is not None else ()
    results = tuple(outcome.order_results) if outcome is not None else ()
    selected_outcome = (
        intents[0].outcome if len(intents) == 1 else None
    )
    expected_outcome = scenario.expected_outcomes[rule.signal_id]
    status = results[0].status if len(results) == 1 else None
    not_attempted = (
        len(results) == 1 and not bool(results[0].attempted)
    )
    signal = outcome.signal if outcome is not None else None
    ok = (
        preparation.ready
        and len(preparation.templates) == 2
        and outcome is not None
        and outcome.status is CoordinationStatus.COMPLETED
        and signal is not None
        and signal.signal_id == simulation_scope_id
        and signal.attributes.get("production_signal_id")
        == rule.signal_id
        and len(intents) == 1
        and selected_outcome is expected_outcome
        and status is ExecutionStatus.DRY_RUN
        and not_attempted
    )
    return {
        "ok": ok,
        "rule_key": rule.rule_key,
        "production_signal_id": rule.signal_id,
        "simulation_scope_id": simulation_scope_id,
        "value_btc": str(signal.value) if signal is not None else None,
        "comparison_op": rule.comparison_op,
        "threshold_btc": str(rule.threshold_btc),
        "prepared_template_count": len(preparation.templates),
        "expected_outcome": expected_outcome.value,
        "selected_outcome": (
            selected_outcome.value
            if selected_outcome is not None
            else None
        ),
        "desired_price": (
            str(intents[0].desired_price) if intents else None
        ),
        "quantity": str(intents[0].quantity) if intents else None,
        "lifecycle_policy": (
            intents[0].lifecycle_policy.kind if intents else None
        ),
        "execution_status": status.value if status is not None else None,
        "execution_attempted": (
            bool(results[0].attempted) if results else None
        ),
        "order_submitted": any(row.attempted for row in results),
    }


def _synthetic_profile(
    *,
    rule: MstrBtcResolutionRule,
    run_id: str,
    scenario_name: str,
    simulation_scope_id: str,
) -> ResolutionExecutionProfile:
    condition_id = "0x" + hashlib.sha256(
        (
            f"mstr-dry-run-condition:{run_id}:"
            f"{scenario_name}:{rule.rule_key}"
        ).encode("utf-8")
    ).hexdigest()
    return ResolutionExecutionProfile(
        profile_key=(
            f"mstr-dry-run-{run_id}-{scenario_name}-{rule.rule_key}"
        ),
        scope_id=simulation_scope_id,
        source_name=MSTR_BTC_SOURCE_NAME,
        source_reference=(
            "https://synthetic.invalid/codexpoly/mstr-btc/"
            f"{run_id}/{scenario_name}/{rule.rule_key}"
        ),
        account_name=_DEFAULT_ACCOUNT_NAME,
        condition_id=condition_id,
        yes_desired_price=_DEFAULT_DESIRED_PRICE,
        no_desired_price=_DEFAULT_DESIRED_PRICE,
        quantity=_DEFAULT_QUANTITY,
        prepare_from=_DETECTED_AT - timedelta(minutes=5),
        expires_at=_DETECTED_AT + timedelta(minutes=15),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            max_reprices=1,
        ),
        metadata={
            "synthetic": True,
            "parser_bypassed": True,
            "production_signal_id": rule.signal_id,
            "rule_key": rule.rule_key,
        },
    )


def _print_json(payload: object, *, stream: object) -> None:
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
