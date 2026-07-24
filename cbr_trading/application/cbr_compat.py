from __future__ import annotations

from typing import Protocol

from cbr_trading.application.coordinator import (
    CoordinationOutcome,
    CoordinationStatus,
)
from cbr_trading.client import DiscoveryResult
from cbr_trading.domain.intents import OrderIntent
from cbr_trading.domain.results import (
    ExecutionStatus,
    OrderExecutionResult,
)
from cbr_trading.pipeline import (
    OrderExecutionResult as LegacyOrderExecutionResult,
)
from cbr_trading.pipeline import OrderIntent as LegacyOrderIntent
from cbr_trading.pipeline import PipelineOutcome
from cbr_trading.strategies.cbr_rate_decision import (
    CbrRateDecisionStrategy,
)


class CbrPollerLike(Protocol):
    def run_once(self) -> DiscoveryResult: ...

    def run_until_published(self) -> DiscoveryResult: ...


class CbrPollModeDiscoveryClient:
    """Present the configured one-shot or continuous poll as one source call."""

    def __init__(
        self,
        poller: CbrPollerLike,
        *,
        wait_until_published: bool,
    ):
        self._poller = poller
        self._wait_until_published = bool(wait_until_published)

    def run_once(self) -> DiscoveryResult:
        if self._wait_until_published:
            return self._poller.run_until_published()
        return self._poller.run_once()


def pipeline_outcome_from_coordination(
    coordination: CoordinationOutcome,
    *,
    release: DiscoveryResult,
    previous_rate: float | None,
    strategy: CbrRateDecisionStrategy,
    rules_load_error: str | None = None,
) -> PipelineOutcome:
    """Retain the legacy JSON and Telegram DTO during runtime migration."""

    if coordination.signal is None:
        raise ValueError("coordination outcome has no resolution signal")
    decision = strategy.evaluate_decision(coordination.signal)
    execution_error = (
        coordination.error
        if coordination.status
        in {
            CoordinationStatus.STRATEGY_ERROR,
            CoordinationStatus.EXECUTION_ERROR,
        }
        else None
    )
    return PipelineOutcome(
        release=release,
        previous_rate=previous_rate,
        change_bps=(
            float(decision.change_bps)
            if decision.change_bps is not None
            else None
        ),
        direction=decision.direction,
        evaluations=decision.evaluations,
        order_results=tuple(
            _legacy_result(result)
            for result in coordination.order_results
        ),
        execution_error=execution_error,
        rules_load_error=rules_load_error,
    )


def _legacy_result(
    result: OrderExecutionResult,
) -> LegacyOrderExecutionResult:
    intent = _legacy_intent(result.intent)
    success: bool | None
    if result.status in {
        ExecutionStatus.SUBMITTED,
        ExecutionStatus.PARTIAL,
    }:
        success = True
    elif result.status in {
        ExecutionStatus.REJECTED,
        ExecutionStatus.FAILED,
    }:
        success = False
    else:
        success = None
    return LegacyOrderExecutionResult(
        intent=intent,
        status=result.status.value,
        attempted=result.attempted,
        success=success,
        order_id=(
            result.orders[0].order_id
            if result.orders
            else None
        ),
        error=result.error,
    )


def _legacy_intent(intent: OrderIntent) -> LegacyOrderIntent:
    return LegacyOrderIntent(
        rule_id=intent.metadata.get("legacy_rule_id"),
        rule_key=str(intent.metadata.get("rule_key") or "default"),
        account_name=intent.account_name,
        condition_id=intent.condition_id,
        action=intent.outcome.value,
        quantity=(
            float(intent.quantity)
            if intent.quantity is not None
            else None
        ),
        limit_price=float(intent.desired_price),
        ready=True,
        reason="ready",
    )
