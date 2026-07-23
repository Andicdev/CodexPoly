from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from cbr_trading.client import DiscoveryResult
from cbr_trading.release import classify_change
from cbr_trading.trading_rules import RuleEvaluation, evaluate_rules


@dataclass(frozen=True)
class OrderIntent:
    """Validated order data produced by a trading rule."""

    rule_id: int | str | None
    rule_key: str
    account_name: str
    condition_id: str
    action: str
    quantity: float | None
    limit_price: float | None
    ready: bool
    reason: str


@dataclass(frozen=True)
class OrderExecutionResult:
    """Result of handing one intent to an order executor."""

    intent: OrderIntent
    status: str
    attempted: bool
    success: bool | None
    order_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PipelineOutcome:
    """Complete result passed to Telegram after order processing."""

    release: DiscoveryResult
    previous_rate: float | None
    change_bps: float | None
    direction: str | None
    evaluations: tuple[RuleEvaluation, ...]
    order_results: tuple[OrderExecutionResult, ...]
    execution_error: str | None = None
    rules_load_error: str | None = None

    @property
    def tradable(self) -> bool:
        return self.change_bps is not None


class OrderExecutor(Protocol):
    def execute(
        self,
        intents: Sequence[OrderIntent],
    ) -> Sequence[OrderExecutionResult]: ...


class DryRunOrderExecutor:
    """Executor with no imports or code paths capable of sending orders."""

    def execute(
        self,
        intents: Sequence[OrderIntent],
    ) -> list[OrderExecutionResult]:
        results: list[OrderExecutionResult] = []
        for intent in intents:
            if not intent.ready:
                results.append(
                    OrderExecutionResult(
                        intent=intent,
                        status="SKIPPED",
                        attempted=False,
                        success=None,
                        error=intent.reason,
                    )
                )
                continue

            results.append(
                OrderExecutionResult(
                    intent=intent,
                    status="DRY_RUN",
                    attempted=False,
                    success=None,
                )
            )
        return results


class TradingPipeline:
    """Evaluate rules, process orders, and notify only afterwards."""

    def __init__(
        self,
        *,
        executor: OrderExecutor,
        notifier: Callable[[PipelineOutcome], Any] | None = None,
    ):
        self.executor = executor
        self.notifier = notifier

    def process(
        self,
        *,
        release: DiscoveryResult,
        previous_rate: float | None,
        subscriptions: Sequence[Mapping[str, Any]],
        rules_load_error: str | None = None,
    ) -> PipelineOutcome:
        change_bps, direction = classify_change(
            previous_rate,
            release.new_rate,
        )

        evaluations: list[RuleEvaluation] = []
        intents: list[OrderIntent] = []
        if change_bps is not None:
            evaluations = evaluate_rules(change_bps, subscriptions)
            intents = [
                build_order_intent(evaluation, subscription)
                for evaluation, subscription in zip(
                    evaluations,
                    subscriptions,
                    strict=True,
                )
                if evaluation.should_trade
            ]

        execution_error: str | None = None
        order_results: tuple[OrderExecutionResult, ...]
        try:
            order_results = tuple(self.executor.execute(intents))
        except Exception as exc:
            execution_error = _safe_exception(exc)
            order_results = ()

        outcome = PipelineOutcome(
            release=release,
            previous_rate=previous_rate,
            change_bps=change_bps,
            direction=direction,
            evaluations=tuple(evaluations),
            order_results=order_results,
            execution_error=execution_error,
            rules_load_error=rules_load_error,
        )

        if self.notifier is not None:
            self.notifier(outcome)
        return outcome


def build_order_intent(
    evaluation: RuleEvaluation,
    subscription: Mapping[str, Any],
) -> OrderIntent:
    account_name = str(subscription.get("account_name") or "").strip()
    condition_id = str(subscription.get("condition_id") or "").strip()
    quantity = _float_or_none(subscription.get("order_qty"))
    limit_price = evaluation.order_price

    problems: list[str] = []
    if not account_name:
        problems.append("missing_account_name")
    if not condition_id:
        problems.append("missing_condition_id")
    if quantity is None or quantity <= 0:
        problems.append("invalid_order_qty")
    if (
        limit_price is None
        or limit_price <= 0
        or limit_price >= 1
    ):
        problems.append("invalid_order_price")

    return OrderIntent(
        rule_id=evaluation.rule_id,
        rule_key=evaluation.rule_key,
        account_name=account_name,
        condition_id=condition_id,
        action=str(evaluation.action or "").upper(),
        quantity=quantity,
        limit_price=limit_price,
        ready=not problems,
        reason="ready" if not problems else ",".join(problems),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_exception(exc: Exception) -> str:
    detail = " ".join(str(exc).split())[:240]
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
