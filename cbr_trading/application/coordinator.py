from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Sequence

from cbr_trading.domain.intents import OrderIntent, OrderTemplate
from cbr_trading.domain.results import OrderExecutionResult
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
    PreparedExecutor,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.sources.base import Source
from cbr_trading.strategies.base import Strategy


class CoordinatorState(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class CoordinationStatus(str, Enum):
    WAITING = "WAITING"
    IGNORED = "IGNORED"
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"
    STRATEGY_ERROR = "STRATEGY_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class CoordinatorLifecycleError(RuntimeError):
    """The coordinator was called in a state where the operation is unsafe."""


@dataclass(frozen=True)
class CoordinationPreparation:
    context: PreparationContext
    templates: tuple[OrderTemplate, ...]
    summary: PreparationSummary
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "templates", tuple(self.templates))
        error = str(self.error or "").strip() or None
        object.__setattr__(self, "error", error)

    @property
    def ready(self) -> bool:
        return self.error is None and self.summary.ready


@dataclass(frozen=True)
class CoordinationOutcome:
    status: CoordinationStatus
    observed_signals: tuple[ResolutionSignal, ...] = ()
    signal: ResolutionSignal | None = None
    intents: tuple[OrderIntent, ...] = ()
    order_results: tuple[OrderExecutionResult, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CoordinationStatus):
            object.__setattr__(
                self,
                "status",
                CoordinationStatus(str(self.status).upper()),
            )
        object.__setattr__(
            self,
            "observed_signals",
            tuple(self.observed_signals),
        )
        object.__setattr__(self, "intents", tuple(self.intents))
        object.__setattr__(
            self,
            "order_results",
            tuple(self.order_results),
        )
        error = str(self.error or "").strip() or None
        if self.status in {
            CoordinationStatus.SOURCE_ERROR,
            CoordinationStatus.STRATEGY_ERROR,
            CoordinationStatus.EXECUTION_ERROR,
        } and error is None:
            raise ValueError("error coordination status requires error")
        if self.status in {
            CoordinationStatus.COMPLETED,
            CoordinationStatus.STRATEGY_ERROR,
            CoordinationStatus.EXECUTION_ERROR,
        } and self.signal is None:
            raise ValueError("resolved coordination status requires signal")
        object.__setattr__(self, "error", error)


class ResolutionTradingCoordinator:
    """Prepare once, poll safely, and execute one event-scoped decision."""

    def __init__(
        self,
        *,
        source: Source,
        strategies: Sequence[Strategy],
        executor: PreparedExecutor,
        context: PreparationContext,
    ):
        self._source = source
        self._strategies = tuple(strategies)
        self._executor = executor
        self._context = context
        self._state = CoordinatorState.CREATED
        self._preparation: CoordinationPreparation | None = None
        self._templates_by_id: dict[str, OrderTemplate] = {}
        self._template_ids_by_strategy: dict[str, set[str]] = {}

    @property
    def state(self) -> CoordinatorState:
        return self._state

    @property
    def preparation(self) -> CoordinationPreparation | None:
        return self._preparation

    def prepare(self) -> CoordinationPreparation:
        self._require_state(CoordinatorState.CREATED, operation="prepare")
        templates: tuple[OrderTemplate, ...] = ()
        try:
            self._validate_topology()
            templates = self._collect_templates()
            raw_summary = self._executor.prepare(
                templates,
                context=self._context,
            )
            summary = _sanitize_preparation_summary(raw_summary)
            self._validate_preparation_summary(
                summary,
                templates=templates,
            )
        except Exception as exc:
            error = redact_exception(exc)
            summary = _failed_preparation_summary(
                templates,
                context=self._context,
                error=error,
            )
            preparation = CoordinationPreparation(
                context=self._context,
                templates=templates,
                summary=summary,
                error=error,
            )
            self._preparation = preparation
            self._state = CoordinatorState.FAILED
            return preparation

        error = None
        if not summary.ready:
            error = "executor_preparation_not_ready"
        preparation = CoordinationPreparation(
            context=self._context,
            templates=templates,
            summary=summary,
            error=error,
        )
        self._preparation = preparation
        self._state = (
            CoordinatorState.READY
            if preparation.ready
            else CoordinatorState.FAILED
        )
        return preparation

    def poll_once(self) -> CoordinationOutcome:
        self._require_state(CoordinatorState.READY, operation="poll_once")
        try:
            observed = tuple(self._source.poll_once())
        except Exception as exc:
            return CoordinationOutcome(
                status=CoordinationStatus.SOURCE_ERROR,
                error=redact_exception(exc),
            )

        contract_error = _validate_source_output(observed)
        if contract_error is not None:
            self._state = CoordinatorState.FAILED
            return CoordinationOutcome(
                status=CoordinationStatus.SOURCE_ERROR,
                observed_signals=tuple(
                    item
                    for item in observed
                    if isinstance(item, ResolutionSignal)
                ),
                error=contract_error,
            )

        if not observed:
            return CoordinationOutcome(
                status=CoordinationStatus.WAITING,
            )

        matching = tuple(
            signal
            for signal in observed
            if self._matches_context(signal)
        )
        if not matching:
            return CoordinationOutcome(
                status=CoordinationStatus.IGNORED,
                observed_signals=observed,
            )

        signal = matching[0]
        try:
            intents = self._evaluate_strategies(signal)
        except Exception as exc:
            self._state = CoordinatorState.FAILED
            return CoordinationOutcome(
                status=CoordinationStatus.STRATEGY_ERROR,
                observed_signals=observed,
                signal=signal,
                error=redact_exception(exc),
            )

        try:
            raw_results = tuple(
                self._executor.execute(intents, signal=signal)
            )
            order_results = _validate_and_sanitize_execution_results(
                raw_results,
                intents=intents,
            )
        except Exception as exc:
            self._state = CoordinatorState.FAILED
            return CoordinationOutcome(
                status=CoordinationStatus.EXECUTION_ERROR,
                observed_signals=observed,
                signal=signal,
                intents=intents,
                error=redact_exception(exc),
            )

        self._state = CoordinatorState.COMPLETED
        return CoordinationOutcome(
            status=CoordinationStatus.COMPLETED,
            observed_signals=observed,
            signal=signal,
            intents=intents,
            order_results=order_results,
        )

    def close(self) -> None:
        if self._state == CoordinatorState.CLOSED:
            return
        try:
            self._executor.close()
        except Exception as exc:
            raise CoordinatorLifecycleError(redact_exception(exc)) from None
        finally:
            self._state = CoordinatorState.CLOSED

    def __enter__(self) -> ResolutionTradingCoordinator:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _validate_topology(self) -> None:
        source_name = str(self._source.source_name or "").strip()
        if not source_name:
            raise ValueError("source_name is required")
        if source_name.casefold() != self._context.source.casefold():
            raise ValueError("preparation_context_source_mismatch")
        if not self._strategies:
            raise ValueError("no_strategies_configured")

        strategy_ids = [
            str(strategy.strategy_id or "").strip()
            for strategy in self._strategies
        ]
        if any(not strategy_id for strategy_id in strategy_ids):
            raise ValueError("strategy_id is required")
        if len({value.casefold() for value in strategy_ids}) != len(
            strategy_ids
        ):
            raise ValueError("duplicate_strategy_id")

    def _collect_templates(self) -> tuple[OrderTemplate, ...]:
        templates: list[OrderTemplate] = []
        templates_by_id: dict[str, OrderTemplate] = {}
        ids_by_strategy: dict[str, set[str]] = {}
        folded_ids: set[str] = set()

        for strategy in self._strategies:
            strategy_id = str(strategy.strategy_id).strip()
            strategy_template_ids: set[str] = set()
            for template in tuple(strategy.order_templates()):
                if not isinstance(template, OrderTemplate):
                    raise TypeError(
                        "strategy templates must contain OrderTemplate objects"
                    )
                if template.strategy_id != strategy_id:
                    raise ValueError("template_strategy_mismatch")
                folded_id = template.template_id.casefold()
                if folded_id in folded_ids:
                    raise ValueError("duplicate_template_id")
                folded_ids.add(folded_id)
                templates.append(template)
                templates_by_id[template.template_id] = template
                strategy_template_ids.add(template.template_id)
            ids_by_strategy[strategy_id] = strategy_template_ids

        if not templates:
            raise ValueError("no_order_templates_configured")
        self._templates_by_id = templates_by_id
        self._template_ids_by_strategy = ids_by_strategy
        return tuple(templates)

    def _validate_preparation_summary(
        self,
        summary: PreparationSummary,
        *,
        templates: Sequence[OrderTemplate],
    ) -> None:
        if not isinstance(summary, PreparationSummary):
            raise TypeError("executor returned invalid preparation summary")
        if summary.context != self._context:
            raise ValueError("executor_preparation_context_mismatch")
        expected_ids = {template.template_id for template in templates}
        actual_ids = {item.template_id for item in summary.items}
        if actual_ids != expected_ids:
            raise ValueError("executor_preparation_templates_mismatch")

    def _matches_context(self, signal: ResolutionSignal) -> bool:
        return (
            signal.source.casefold() == self._context.source.casefold()
            and signal.signal_id == self._context.scope_id
        )

    def _evaluate_strategies(
        self,
        signal: ResolutionSignal,
    ) -> tuple[OrderIntent, ...]:
        intents: list[OrderIntent] = []
        seen_intent_ids: set[str] = set()
        seen_template_ids: set[str] = set()

        for strategy in self._strategies:
            strategy_id = str(strategy.strategy_id).strip()
            allowed_template_ids = self._template_ids_by_strategy[
                strategy_id
            ]
            for intent in tuple(strategy.evaluate(signal)):
                if not isinstance(intent, OrderIntent):
                    raise TypeError(
                        "strategy evaluation must contain OrderIntent objects"
                    )
                if intent.strategy_id != strategy_id:
                    raise ValueError("intent_strategy_mismatch")
                if intent.signal_id != signal.signal_id:
                    raise ValueError("intent_signal_mismatch")
                if intent.template_id not in allowed_template_ids:
                    raise ValueError("intent_template_not_prepared")
                template = self._templates_by_id[intent.template_id]
                if intent != template.bind(signal_id=signal.signal_id):
                    raise ValueError("intent_parameters_mismatch")

                folded_intent_id = intent.intent_id.casefold()
                folded_template_id = intent.template_id.casefold()
                if folded_intent_id in seen_intent_ids:
                    raise ValueError("duplicate_intent_id")
                if folded_template_id in seen_template_ids:
                    raise ValueError("duplicate_selected_template")
                seen_intent_ids.add(folded_intent_id)
                seen_template_ids.add(folded_template_id)
                intents.append(intent)
        return tuple(intents)

    def _require_state(
        self,
        expected: CoordinatorState,
        *,
        operation: str,
    ) -> None:
        if self._state != expected:
            raise CoordinatorLifecycleError(
                f"{operation} requires {expected.value} state; "
                f"current state is {self._state.value}"
            )


def _validate_source_output(
    observed: Sequence[object],
) -> str | None:
    if any(not isinstance(item, ResolutionSignal) for item in observed):
        return "source_contract_invalid_signal"
    signal_ids = [
        item.signal_id
        for item in observed
        if isinstance(item, ResolutionSignal)
    ]
    if len(signal_ids) != len(set(signal_ids)):
        return "source_contract_duplicate_signal_id"
    return None


def _sanitize_preparation_summary(
    summary: PreparationSummary,
) -> PreparationSummary:
    if not isinstance(summary, PreparationSummary):
        raise TypeError("executor returned invalid preparation summary")
    return PreparationSummary(
        items=tuple(
                PreparationItem(
                    template_id=item.template_id,
                    status=item.status,
                    prepared_key=(
                        redact_sensitive_text(item.prepared_key)
                        if item.prepared_key
                        else None
                    ),
                error=(
                    redact_sensitive_text(item.error)
                    if item.error
                    else None
                ),
            )
            for item in summary.items
        ),
        context=summary.context,
    )


def _failed_preparation_summary(
    templates: Sequence[OrderTemplate],
    *,
    context: PreparationContext,
    error: str,
) -> PreparationSummary:
    safe_error = redact_sensitive_text(error)
    return PreparationSummary(
        items=tuple(
            PreparationItem(
                template_id=template.template_id,
                status=PreparationStatus.FAILED,
                error=safe_error,
            )
            for template in templates
        ),
        context=context,
    )


def _validate_and_sanitize_execution_results(
    results: Sequence[object],
    *,
    intents: Sequence[OrderIntent],
) -> tuple[OrderExecutionResult, ...]:
    if len(results) != len(intents):
        raise ValueError("executor_result_count_mismatch")

    sanitized: list[OrderExecutionResult] = []
    for result, intent in zip(results, intents, strict=True):
        if not isinstance(result, OrderExecutionResult):
            raise TypeError("executor returned invalid order result")
        if result.intent != intent:
            raise ValueError("executor_result_intent_mismatch")
        sanitized.append(
            replace(
                result,
                error=(
                    redact_sensitive_text(result.error)
                    if result.error
                    else None
                ),
            )
        )
    return tuple(sanitized)
