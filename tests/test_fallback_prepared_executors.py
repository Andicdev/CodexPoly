from __future__ import annotations

import unittest
from dataclasses import replace

from cbr_trading.domain import ExecutionStatus
from cbr_trading.execution import (
    DryRunPreparedExecutor,
    UnavailablePreparedExecutor,
)
from tests.test_resolution_coordinator import (
    _context,
    _signal,
    _template,
)


class FallbackPreparedExecutorTests(unittest.TestCase):
    def test_dry_run_prepares_and_returns_unattempted_results(self) -> None:
        template = _template()
        signal = _signal()
        executor = DryRunPreparedExecutor()

        preparation = executor.prepare(
            (template,),
            context=_context(),
        )
        results = executor.execute(
            (template.bind(signal_id=signal.signal_id),),
            signal=signal,
        )

        self.assertTrue(preparation.ready)
        self.assertEqual(results[0].status, ExecutionStatus.DRY_RUN)
        self.assertFalse(results[0].attempted)

    def test_unavailable_executor_sanitizes_reason(self) -> None:
        template = _template()
        signal = _signal()
        executor = UnavailablePreparedExecutor(
            "DATABASE_URL=hidden-value"
        )
        executor.prepare((template,), context=_context())

        results = executor.execute(
            (template.bind(signal_id=signal.signal_id),),
            signal=signal,
        )

        self.assertEqual(results[0].status, ExecutionStatus.SKIPPED)
        self.assertNotIn("hidden-value", results[0].error or "")
        self.assertIn("[REDACTED]", results[0].error or "")

    def test_wrong_scope_does_not_consume_executor(self) -> None:
        template = _template()
        signal = _signal()
        intent = template.bind(signal_id=signal.signal_id)
        executor = DryRunPreparedExecutor()
        executor.prepare((template,), context=_context())

        wrong = executor.execute(
            (intent,),
            signal=replace(signal, signal_id="source:event:other"),
        )
        accepted = executor.execute((intent,), signal=signal)

        self.assertEqual(wrong[0].status, ExecutionStatus.SKIPPED)
        self.assertEqual(
            wrong[0].error,
            "prepared_signal_scope_mismatch",
        )
        self.assertEqual(accepted[0].status, ExecutionStatus.DRY_RUN)


if __name__ == "__main__":
    unittest.main()
