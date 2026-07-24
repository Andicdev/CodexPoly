from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from cbr_trading.domain.intents import (
    OrderIntent,
    OrderTemplate,
    RepriceOnTickChange,
)
from cbr_trading.domain.results import (
    ExecutionStatus,
    OrderExecutionResult,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.order_supervisor import OrderSupervisor
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationSummary,
    PreparedExecutor,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)


class SupervisedPreparedExecutor:
    """Register known replaceable orders immediately after submission."""

    def __init__(
        self,
        delegate: PreparedExecutor,
        *,
        supervisor: OrderSupervisor,
    ):
        self._delegate = delegate
        self._supervisor = supervisor

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
        results = tuple(
            self._delegate.execute(intents, signal=signal)
        )
        supervised: list[OrderExecutionResult] = []
        for result in results:
            policy = result.intent.lifecycle_policy
            if (
                result.attempted
                and result.handle is not None
                and result.orders
                and isinstance(policy, RepriceOnTickChange)
            ):
                try:
                    self._supervisor.register(
                        result.handle,
                        policy=policy,
                    )
                except Exception as exc:
                    supervised.append(
                        replace(
                            result,
                            status=ExecutionStatus.AMBIGUOUS,
                            error=_registration_error(
                                existing=result.error,
                                exc=exc,
                            ),
                        )
                    )
                    continue
            supervised.append(result)
        return tuple(supervised)

    def close(self) -> None:
        self._delegate.close()


def _registration_error(
    *,
    existing: str | None,
    exc: Exception,
) -> str:
    parts = [
        str(existing or "").strip(),
        (
            "order_supervision_registration_failed: "
            f"{redact_exception(exc)}"
        ),
    ]
    return redact_sensitive_text(
        "; ".join(part for part in parts if part),
        max_length=500,
    )
