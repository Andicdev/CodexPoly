from __future__ import annotations

from dataclasses import replace
from typing import Callable, Sequence

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
        on_registered: Callable[[], None] | None = None,
    ):
        self._delegate = delegate
        self._supervisor = supervisor
        self._on_registered = on_registered

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
        registered = False
        for result in results:
            policy = result.intent.lifecycle_policy
            if (
                result.attempted
                and result.handle is not None
                and result.orders
                and isinstance(policy, RepriceOnTickChange)
                and any(
                    order.effective_price
                    != result.handle.desired_price
                    for order in result.orders
                )
            ):
                try:
                    self._supervisor.register(
                        result.handle,
                        policy=policy,
                    )
                    registered = True
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
        if registered and self._on_registered is not None:
            # Registration is durable. A failed best-effort wakeup must not
            # turn an accepted live order into an ambiguous execution; the
            # periodic watch refresh remains the fallback.
            try:
                self._on_registered()
            except Exception:
                pass
        return tuple(supervised)

    def close(self) -> None:
        self._delegate.close()

    def expire_pending(
        self,
        *,
        reason: str = "preparation_window_expired",
    ) -> None:
        expire = getattr(self._delegate, "expire_pending", None)
        if callable(expire):
            expire(reason=reason)


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
