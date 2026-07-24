from __future__ import annotations

from typing import Sequence

from cbr_trading.domain.intents import OrderIntent, OrderTemplate
from cbr_trading.domain.results import (
    ExecutionStatus,
    OrderExecutionResult,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.secret_guard import redact_sensitive_text


class DryRunPreparedExecutor:
    """Exercise the complete prepared flow without submitting orders."""

    def __init__(self):
        self._delegate = _NonSubmittingPreparedExecutor(
            status=ExecutionStatus.DRY_RUN,
            prepared_prefix="dry-run",
            reason=None,
        )

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        return self._delegate.prepare(templates, context=context)

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        return self._delegate.execute(intents, signal=signal)

    def close(self) -> None:
        self._delegate.close()


class UnavailablePreparedExecutor:
    """Fail closed while preserving source monitoring and result shape."""

    def __init__(self, reason: str):
        safe_reason = redact_sensitive_text(reason)
        if not safe_reason:
            raise ValueError("unavailable executor reason is required")
        self._delegate = _NonSubmittingPreparedExecutor(
            status=ExecutionStatus.SKIPPED,
            prepared_prefix="unavailable",
            reason=safe_reason,
        )

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        return self._delegate.prepare(templates, context=context)

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        return self._delegate.execute(intents, signal=signal)

    def close(self) -> None:
        self._delegate.close()


class _NonSubmittingPreparedExecutor:
    def __init__(
        self,
        *,
        status: ExecutionStatus,
        prepared_prefix: str,
        reason: str | None,
    ):
        self._status = status
        self._prepared_prefix = prepared_prefix
        self._reason = reason
        self._context: PreparationContext | None = None
        self._templates: dict[str, OrderTemplate] = {}
        self._execution_started = False
        self._closed = False

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        rows = tuple(templates)
        if self._closed:
            return PreparationSummary(
                items=tuple(
                    PreparationItem(
                        template_id=template.template_id,
                        status=PreparationStatus.FAILED,
                        error="executor_closed",
                    )
                    for template in rows
                ),
                context=context,
            )
        if self._context is not None:
            return PreparationSummary(
                items=tuple(
                    PreparationItem(
                        template_id=template.template_id,
                        status=PreparationStatus.FAILED,
                        error="executor_already_prepared",
                    )
                    for template in rows
                ),
                context=context,
            )
        self._context = context
        self._templates = {
            template.template_id: template
            for template in rows
        }
        if len(self._templates) != len(rows):
            return PreparationSummary(
                items=tuple(
                    PreparationItem(
                        template_id=template.template_id,
                        status=PreparationStatus.FAILED,
                        error="duplicate_template_id",
                    )
                    for template in self._templates.values()
                ),
                context=context,
            )
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=(
                        f"{self._prepared_prefix}:"
                        f"{context.scope_id}/{template.template_id}"
                    ),
                )
                for template in rows
            ),
            context=context,
        )

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        rows = tuple(intents)
        if self._closed:
            return self._skipped(rows, "executor_closed")
        if self._context is None:
            return self._skipped(rows, "executor_not_prepared")
        if self._execution_started:
            return self._skipped(rows, "executor_already_used")
        if (
            signal.source.casefold()
            != self._context.source.casefold()
            or signal.signal_id != self._context.scope_id
        ):
            return self._skipped(rows, "prepared_signal_scope_mismatch")

        invalid: dict[int, str] = {}
        for index, intent in enumerate(rows):
            template = self._templates.get(intent.template_id)
            if template is None:
                invalid[index] = "prepared_template_missing"
            elif intent != template.bind(signal_id=signal.signal_id):
                invalid[index] = "prepared_intent_parameters_mismatch"

        self._execution_started = True
        return tuple(
            OrderExecutionResult(
                intent=intent,
                status=(
                    ExecutionStatus.SKIPPED
                    if index in invalid
                    else self._status
                ),
                attempted=False,
                error=(
                    invalid[index]
                    if index in invalid
                    else self._reason
                ),
            )
            for index, intent in enumerate(rows)
        )

    def close(self) -> None:
        self._closed = True

    @staticmethod
    def _skipped(
        intents: Sequence[OrderIntent],
        error: str,
    ) -> tuple[OrderExecutionResult, ...]:
        return tuple(
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.SKIPPED,
                attempted=False,
                error=error,
            )
            for intent in intents
        )
