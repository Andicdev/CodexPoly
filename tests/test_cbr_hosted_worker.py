from __future__ import annotations

import unittest

from cbr_trading.hosted_worker import main


class HostedWorkerTests(unittest.TestCase):
    def test_runner_failure_is_returned_without_idle_loop(self) -> None:
        sleeps: list[float] = []

        exit_code = main(
            runner=lambda: 5,
            sleep=lambda seconds: sleeps.append(seconds),
        )

        self.assertEqual(exit_code, 5)
        self.assertEqual(sleeps, [])

    def test_successful_event_stays_idle_until_stopped(self) -> None:
        sleeps: list[float] = []

        def stop_after_first_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            raise KeyboardInterrupt

        exit_code = main(
            runner=lambda: 0,
            sleep=stop_after_first_sleep,
        )

        self.assertEqual(exit_code, 130)
        self.assertEqual(sleeps, [300])


if __name__ == "__main__":
    unittest.main()
