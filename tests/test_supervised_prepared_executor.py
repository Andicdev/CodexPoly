from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import (
    ExecutionHandle,
    ExecutionStatus,
    KeepOpenPolicy,
    OrderExecutionResult,
    OrderSide,
    OrderTemplate,
    Outcome,
    PlacedOrder,
    RepriceOnTickChange,
    ResolutionSignal,
)
from cbr_trading.execution import (
    PreparationContext,
    PreparationSummary,
    SupervisedPreparedExecutor,
)


def _policy() -> RepriceOnTickChange:
    return RepriceOnTickChange(
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
    )


def _template(
    *,
    policy: object | None = None,
) -> OrderTemplate:
    return OrderTemplate(
        template_id="template-1",
        strategy_id="strategy-1",
        account_name="primary",
        condition_id="condition-1",
        outcome=Outcome.YES,
        side=OrderSide.BUY,
        desired_price=Decimal("0.999"),
        quantity=Decimal("10"),
        lifecycle_policy=policy or _policy(),
    )


def _signal() -> ResolutionSignal:
    return ResolutionSignal(
        signal_id="signal-1",
        source="test",
        subject="subject",
        metric="metric",
        value=Decimal("1"),
        unit="value",
        detected_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def _result(
    template: OrderTemplate,
    *,
    effective_price: Decimal = Decimal("0.99"),
) -> OrderExecutionResult:
    intent = template.bind(signal_id="signal-1")
    order = PlacedOrder(
        order_id="order-1",
        asset_id="asset-yes",
        effective_price=effective_price,
        quantity=Decimal("10"),
    )
    handle = ExecutionHandle(
        order_group_id="group-1",
        intent_id=intent.intent_id,
        account_name=intent.account_name,
        condition_id=intent.condition_id,
        outcome=intent.outcome,
        asset_id=order.asset_id,
        live_order_ids=(order.order_id,),
        signal_id=intent.signal_id,
        template_id=intent.template_id,
        strategy_id=intent.strategy_id,
        side=intent.side,
        desired_price=intent.desired_price,
        quantity=intent.quantity,
    )
    return OrderExecutionResult(
        intent=intent,
        status=ExecutionStatus.SUBMITTED,
        attempted=True,
        orders=(order,),
        handle=handle,
    )


class _Delegate:
    def __init__(self, result: OrderExecutionResult):
        self.result = result
        self.closed = False

    def prepare(
        self,
        templates: object,
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        return PreparationSummary(items=(), context=context)

    def execute(
        self,
        intents: object,
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        return (self.result,)

    def close(self) -> None:
        self.closed = True


class _Supervisor:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.registrations = []
        self.closed = False

    def register(self, handle: object, *, policy: object) -> None:
        self.registrations.append((handle, policy))
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True


class SupervisedPreparedExecutorTests(unittest.TestCase):
    def test_registers_replaceable_submitted_handle(self) -> None:
        template = _template()
        result = _result(template)
        delegate = _Delegate(result)
        supervisor = _Supervisor()
        executor = SupervisedPreparedExecutor(
            delegate,
            supervisor=supervisor,
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual, (result,))
        self.assertEqual(
            supervisor.registrations,
            [(result.handle, template.lifecycle_policy)],
        )

    def test_wakes_watch_runtime_after_durable_registration(self) -> None:
        template = _template()
        result = _result(template)
        supervisor = _Supervisor()
        wake_calls: list[str] = []
        executor = SupervisedPreparedExecutor(
            _Delegate(result),
            supervisor=supervisor,
            on_registered=lambda: wake_calls.append("wake"),
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual, (result,))
        self.assertEqual(wake_calls, ["wake"])

    def test_wakeup_failure_keeps_accepted_order_result(self) -> None:
        template = _template()
        result = _result(template)

        def fail_wakeup() -> None:
            raise RuntimeError("wake failed")

        executor = SupervisedPreparedExecutor(
            _Delegate(result),
            supervisor=_Supervisor(),
            on_registered=fail_wakeup,
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual, (result,))

    def test_keep_open_result_is_not_persisted_for_supervision(self) -> None:
        template = _template(policy=KeepOpenPolicy())
        result = _result(template)
        supervisor = _Supervisor()
        executor = SupervisedPreparedExecutor(
            _Delegate(result),
            supervisor=supervisor,
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual, (result,))
        self.assertEqual(supervisor.registrations, [])

    def test_order_already_at_desired_price_needs_no_supervision(
        self,
    ) -> None:
        template = _template()
        result = _result(
            template,
            effective_price=Decimal("0.999"),
        )
        supervisor = _Supervisor()
        executor = SupervisedPreparedExecutor(
            _Delegate(result),
            supervisor=supervisor,
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual, (result,))
        self.assertEqual(supervisor.registrations, [])

    def test_registration_failure_marks_known_order_ambiguous(self) -> None:
        template = _template()
        result = _result(template)
        supervisor = _Supervisor(
            error=RuntimeError(
                "DATABASE_URL=postgres://user:password@example/db"
            )
        )
        executor = SupervisedPreparedExecutor(
            _Delegate(result),
            supervisor=supervisor,
        )

        actual = executor.execute(
            (result.intent,),
            signal=_signal(),
        )

        self.assertEqual(actual[0].status, ExecutionStatus.AMBIGUOUS)
        self.assertEqual(actual[0].handle, result.handle)
        self.assertNotIn("password", actual[0].error or "")
        self.assertIn(
            "order_supervision_registration_failed",
            actual[0].error or "",
        )

    def test_close_does_not_close_shared_supervisor(self) -> None:
        template = _template()
        delegate = _Delegate(_result(template))
        supervisor = _Supervisor()
        executor = SupervisedPreparedExecutor(
            delegate,
            supervisor=supervisor,
        )

        executor.close()

        self.assertTrue(delegate.closed)
        self.assertFalse(supervisor.closed)


if __name__ == "__main__":
    unittest.main()
