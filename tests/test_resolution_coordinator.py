from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.application import (
    CoordinationStatus,
    CoordinatorLifecycleError,
    CoordinatorState,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import (
    ExecutionStatus,
    OrderExecutionResult,
    OrderSide,
    OrderTemplate,
    Outcome,
    ResolutionSignal,
)
from cbr_trading.execution import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
    cbr_preparation_context,
)
from cbr_trading.sources.cbr import CbrResolutionSource
from cbr_trading.strategies.cbr_rate_decision import (
    CbrRateDecisionStrategy,
)
from tests.test_cbr_contract_adapters import _discovery, _subscription


def _signal(
    *,
    signal_id: str = "source:event:1",
    source: str = "source",
) -> ResolutionSignal:
    return ResolutionSignal(
        signal_id=signal_id,
        source=source,
        subject="subject",
        metric="metric",
        value=Decimal("1"),
        detected_at=datetime(2026, 7, 24, 13, 30, tzinfo=timezone.utc),
    )


def _context() -> PreparationContext:
    return PreparationContext(
        scope_id="source:event:1",
        source="source",
        source_reference="https://example.test/event/1",
    )


def _template(
    *,
    template_id: str = "strategy.one:YES",
    strategy_id: str = "strategy.one",
) -> OrderTemplate:
    return OrderTemplate(
        template_id=template_id,
        strategy_id=strategy_id,
        account_name="primary",
        condition_id="condition-1",
        outcome=Outcome.YES,
        side=OrderSide.BUY,
        desired_price=Decimal("0.99"),
        quantity=Decimal("10"),
    )


class _Source:
    source_name = "source"

    def __init__(self, batches, *, trace: list[str] | None = None):
        self.batches = list(batches)
        self.trace = trace
        self.calls = 0

    def poll_once(self):
        self.calls += 1
        if self.trace is not None:
            self.trace.append("poll")
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch


class _Strategy:
    strategy_id = "strategy.one"

    def __init__(
        self,
        *,
        strategy_id: str = "strategy.one",
        templates=None,
        evaluator=None,
        trace: list[str] | None = None,
    ):
        self.strategy_id = strategy_id
        self.templates = tuple(
            templates
            or (
                _template(
                    template_id=f"{strategy_id}:YES",
                    strategy_id=strategy_id,
                ),
            )
        )
        self.evaluator = evaluator
        self.trace = trace

    def order_templates(self):
        if self.trace is not None:
            self.trace.append("templates")
        return self.templates

    def evaluate(self, signal):
        if self.trace is not None:
            self.trace.append("evaluate")
        if self.evaluator is not None:
            return self.evaluator(signal)
        return (self.templates[0].bind(signal_id=signal.signal_id),)


class _Executor:
    def __init__(
        self,
        *,
        trace: list[str] | None = None,
        preparation_summary=None,
        preparation_error: Exception | None = None,
        execution_error: Exception | None = None,
        result_count_mismatch: bool = False,
    ):
        self.trace = trace
        self.preparation_summary = preparation_summary
        self.preparation_error = preparation_error
        self.execution_error = execution_error
        self.result_count_mismatch = result_count_mismatch
        self.prepare_calls = []
        self.execute_calls = []
        self.close_calls = 0

    def prepare(self, templates, *, context):
        templates = tuple(templates)
        self.prepare_calls.append((templates, context))
        if self.trace is not None:
            self.trace.append("prepare")
        if self.preparation_error is not None:
            raise self.preparation_error
        if self.preparation_summary is not None:
            return self.preparation_summary
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=(
                        f"{context.scope_id}/{template.template_id}"
                    ),
                )
                for template in templates
            ),
            context=context,
        )

    def execute(self, intents, *, signal):
        intents = tuple(intents)
        self.execute_calls.append((intents, signal))
        if self.trace is not None:
            self.trace.append("execute")
        if self.execution_error is not None:
            raise self.execution_error
        if self.result_count_mismatch:
            return ()
        return tuple(
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.DRY_RUN,
                attempted=False,
            )
            for intent in intents
        )

    def close(self):
        self.close_calls += 1
        if self.trace is not None:
            self.trace.append("close")


def _coordinator(
    *,
    source=None,
    strategy=None,
    executor=None,
    context=None,
):
    return ResolutionTradingCoordinator(
        source=source or _Source([(_signal(),)]),
        strategies=(strategy or _Strategy(),),
        executor=executor or _Executor(),
        context=context or _context(),
    )


class ResolutionTradingCoordinatorTests(unittest.TestCase):
    def test_successful_lifecycle_has_strict_order(self) -> None:
        trace: list[str] = []
        source = _Source([(_signal(),)], trace=trace)
        strategy = _Strategy(trace=trace)
        executor = _Executor(trace=trace)
        coordinator = _coordinator(
            source=source,
            strategy=strategy,
            executor=executor,
        )

        preparation = coordinator.prepare()
        outcome = coordinator.poll_once()

        self.assertTrue(preparation.ready)
        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        self.assertEqual(len(outcome.intents), 1)
        self.assertEqual(len(outcome.order_results), 1)
        self.assertEqual(coordinator.state, CoordinatorState.COMPLETED)
        self.assertEqual(
            trace,
            ["templates", "prepare", "poll", "evaluate", "execute"],
        )

    def test_multiple_strategies_share_one_preparation_and_execution(self) -> None:
        first = _Strategy(strategy_id="strategy.one")
        second = _Strategy(strategy_id="strategy.two")
        executor = _Executor()
        coordinator = ResolutionTradingCoordinator(
            source=_Source([(_signal(),)]),
            strategies=(first, second),
            executor=executor,
            context=_context(),
        )

        preparation = coordinator.prepare()
        outcome = coordinator.poll_once()

        self.assertEqual(len(preparation.templates), 2)
        self.assertEqual(len(executor.prepare_calls), 1)
        self.assertEqual(len(outcome.intents), 2)
        self.assertEqual(len(executor.execute_calls), 1)
        self.assertEqual(
            {
                intent.strategy_id
                for intent in executor.execute_calls[0][0]
            },
            {"strategy.one", "strategy.two"},
        )

    def test_waiting_and_wrong_scope_do_not_consume_preparation(self) -> None:
        source = _Source(
            [
                (),
                (_signal(signal_id="source:event:other"),),
                (_signal(),),
            ]
        )
        executor = _Executor()
        coordinator = _coordinator(source=source, executor=executor)
        coordinator.prepare()

        waiting = coordinator.poll_once()
        ignored = coordinator.poll_once()
        completed = coordinator.poll_once()

        self.assertEqual(waiting.status, CoordinationStatus.WAITING)
        self.assertEqual(ignored.status, CoordinationStatus.IGNORED)
        self.assertEqual(completed.status, CoordinationStatus.COMPLETED)
        self.assertEqual(len(executor.execute_calls), 1)

    def test_source_exception_is_sanitized_and_can_be_retried(self) -> None:
        source = _Source(
            [
                RuntimeError("DATABASE_URL=hidden-value"),
                (_signal(),),
            ]
        )
        coordinator = _coordinator(source=source)
        coordinator.prepare()

        failed_poll = coordinator.poll_once()
        completed = coordinator.poll_once()

        self.assertEqual(
            failed_poll.status,
            CoordinationStatus.SOURCE_ERROR,
        )
        self.assertNotIn("hidden-value", failed_poll.error or "")
        self.assertIn("[REDACTED]", failed_poll.error or "")
        self.assertEqual(completed.status, CoordinationStatus.COMPLETED)

    def test_duplicate_source_signal_is_terminal_contract_error(self) -> None:
        signal = _signal()
        coordinator = _coordinator(
            source=_Source([(signal, signal)]),
        )
        coordinator.prepare()

        outcome = coordinator.poll_once()

        self.assertEqual(outcome.status, CoordinationStatus.SOURCE_ERROR)
        self.assertEqual(
            outcome.error,
            "source_contract_duplicate_signal_id",
        )
        self.assertEqual(coordinator.state, CoordinatorState.FAILED)

    def test_empty_strategy_selection_still_releases_executor(self) -> None:
        strategy = _Strategy(evaluator=lambda _: ())
        executor = _Executor()
        coordinator = _coordinator(
            strategy=strategy,
            executor=executor,
        )
        coordinator.prepare()

        outcome = coordinator.poll_once()

        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        self.assertEqual(outcome.intents, ())
        self.assertEqual(executor.execute_calls[0][0], ())

    def test_context_source_mismatch_fails_before_executor_prepare(self) -> None:
        executor = _Executor()
        context = replace(_context(), source="another-source")
        coordinator = _coordinator(
            executor=executor,
            context=context,
        )

        preparation = coordinator.prepare()

        self.assertFalse(preparation.ready)
        self.assertIn(
            "preparation_context_source_mismatch",
            preparation.error or "",
        )
        self.assertEqual(executor.prepare_calls, [])
        self.assertEqual(coordinator.state, CoordinatorState.FAILED)

    def test_executor_preparation_must_cover_exact_templates(self) -> None:
        summary = PreparationSummary(items=(), context=_context())
        executor = _Executor(preparation_summary=summary)
        coordinator = _coordinator(executor=executor)

        preparation = coordinator.prepare()

        self.assertFalse(preparation.ready)
        self.assertIn(
            "executor_preparation_templates_mismatch",
            preparation.error or "",
        )
        self.assertEqual(coordinator.state, CoordinatorState.FAILED)

    def test_strategy_cannot_mutate_prepared_intent(self) -> None:
        template = _template()

        def mutated(signal):
            return (
                replace(
                    template.bind(signal_id=signal.signal_id),
                    desired_price=Decimal("0.98"),
                ),
            )

        executor = _Executor()
        coordinator = _coordinator(
            strategy=_Strategy(
                templates=(template,),
                evaluator=mutated,
            ),
            executor=executor,
        )
        coordinator.prepare()

        outcome = coordinator.poll_once()

        self.assertEqual(
            outcome.status,
            CoordinationStatus.STRATEGY_ERROR,
        )
        self.assertIn("intent_parameters_mismatch", outcome.error or "")
        self.assertEqual(executor.execute_calls, [])
        self.assertEqual(coordinator.state, CoordinatorState.FAILED)

    def test_execution_exception_is_terminal_and_sanitized(self) -> None:
        executor = _Executor(
            execution_error=RuntimeError("PRIVATE_KEY=hidden-value")
        )
        coordinator = _coordinator(executor=executor)
        coordinator.prepare()

        outcome = coordinator.poll_once()

        self.assertEqual(
            outcome.status,
            CoordinationStatus.EXECUTION_ERROR,
        )
        self.assertNotIn("hidden-value", outcome.error or "")
        self.assertIn("[REDACTED]", outcome.error or "")
        with self.assertRaises(CoordinatorLifecycleError):
            coordinator.poll_once()

    def test_execution_result_count_mismatch_is_terminal(self) -> None:
        coordinator = _coordinator(
            executor=_Executor(result_count_mismatch=True),
        )
        coordinator.prepare()

        outcome = coordinator.poll_once()

        self.assertEqual(
            outcome.status,
            CoordinationStatus.EXECUTION_ERROR,
        )
        self.assertIn("executor_result_count_mismatch", outcome.error or "")
        self.assertEqual(coordinator.state, CoordinatorState.FAILED)

    def test_close_is_idempotent(self) -> None:
        executor = _Executor()
        coordinator = _coordinator(executor=executor)

        coordinator.close()
        coordinator.close()

        self.assertEqual(executor.close_calls, 1)
        self.assertEqual(coordinator.state, CoordinatorState.CLOSED)

    def test_real_cbr_source_and_strategy_run_through_coordinator(self) -> None:
        release = _discovery()

        class DiscoveryClient:
            def run_once(self):
                return release

        source = CbrResolutionSource(
            DiscoveryClient(),
            previous_rate_provider=lambda: Decimal("14.5"),
            clock=lambda: datetime(
                2026,
                7,
                24,
                13,
                30,
                1,
                tzinfo=timezone.utc,
            ),
        )
        strategy = CbrRateDecisionStrategy([_subscription()])
        executor = _Executor()
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=cbr_preparation_context(release.url),
        )

        preparation = coordinator.prepare()
        outcome = coordinator.poll_once()

        self.assertTrue(preparation.ready)
        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        self.assertEqual(len(outcome.intents), 1)
        self.assertEqual(outcome.intents[0].outcome, Outcome.YES)
        self.assertEqual(len(executor.execute_calls), 1)


if __name__ == "__main__":
    unittest.main()
